from twisted.internet.protocol import Protocol,Factory,ClientFactory
from twisted.protocols import basic
import remote_server
from bridge import BridgeClientFactory, SafeBridgeClient
from proxy import ProxyClient,proxy_connect
from cbconnection import CBConnectionClient
import sys,threading
from twisted.python import log
from twisted.internet import defer

PORT = 8585

class Stat:
	def __init__(self):
		self.send_bytes = 0
		self.receive_bytes = 0

class LocalServer(basic.LineReceiver, ProxyClient, CBConnectionClient):
	def __init__(self):
		ProxyClient.__init__(self)
		CBConnectionClient.__init__(self)
		self._first_line_received = False
		self._headers = {}
		self._header_lines = []
		self._pending_data_arr = []
		self.auto_proxy = False
		self.initial_go_bridge = None
		self.dest_host = None
		self.dest_port = None
		self.failed_count = 0
		self.delayed_call = None
		self.stat = Stat()
		self._proxy_connected = False
		self._cb_connected = False

	def lineReceived(self, line):
		self._header_lines.append(line)
		if not line:
			if not self._first_line_received:
				self.respondBadRequest()
				return
			host = None
			port = 80
			#check http path
			request_host = None
			if self._command == 'CONNECT':
				request_host = self._request
			scheme_headers = ['http://', 'https://']
			for scheme_header in scheme_headers:
				if self._request.startswith(scheme_header):
					p = self._request.find('/', len(scheme_header))
					if p == -1:
						p = len(self._request)
					request_host = self._request[len(scheme_header):p]
			if request_host:
				if ':' in request_host:
					host, port_str = request_host.split(':')
					port = int(port_str)
				else:
					host = request_host
			#check host header
			host_header = self._headers.get('host')
			if host_header:
				if ':' in host_header:
					log.msg(host_header)
					host,port_str = host_header.split(':')
					if not port_str.isdigit():
						self.respondBadRequest()
						return
					port = int(port_str)
				else:
					host = host_header
			if host is None or port is None:
				self.respondBadRequest()
				return
			#avoid infinite loop
			if port == PORT:
				self.respondBadRequest()
				return
			
			if self._command != 'CONNECT':
				#add a new line
				self._header_lines.append('')
				self._pending_data_arr.append('\r\n'.join(self._header_lines))
			else:
				self.transport.write('HTTP/1.1 200 OK\r\n\r\n')

			mode = self.factory.mode
			auto_proxy = mode == self.factory.AUTO
			go_bridge = None
			if auto_proxy:
				go_bridge = self.factory.should_go_bridge(host)
			log.msg('%s %d go_bridge:%s auto_proxy:%d'%(host, port, go_bridge, auto_proxy))
			self.host = host
			self.port = port
			self.auto_proxy = auto_proxy
			self.initial_go_bridge = go_bridge

			if mode == self.factory.BRIDGE or go_bridge is True:
				self.try_cb_connect()
			elif mode == self.factory.DIRECT or go_bridge is False:
				proxy_connect(host, port ,self)
			else:
				assert auto_proxy and go_bridge is None
				# try both, first direct, then cb_connect
				proxy_connect(host, port, self)
				from twisted.internet import reactor
				self.delayed_call = reactor.callLater(1, self.try_cb_connect)

			self.setRawMode()
		elif not self._first_line_received:
			parts = line.split()
			if len(parts) != 3:
				self.respondBadRequest()
				return
			self._command, self._request, self._version = parts
			self._first_line_received = True
			#only keep path
			if self._request.startswith('http://'):
				path_start = self._request.find('/', len('http://'))
				if path_start == -1:
					path = '/'
				else:
					path = self._request[path_start:]
				assert len(self._header_lines) == 1
				line = ' '.join((self._command, path, self._version))
				self._header_lines[0] = line
			log.msg(line)
		else:
			header, data = line.split(b':', 1)
			header = header.lower()
			data = data.strip()
			self._headers[header] = data

	def rawDataReceived(self, data):
		log.msg('rawDataReceived %s (%d)' % (repr(data[:20]), len(data)))
		# object exists means we can send data
		if self.cb_connection:
			self.cb_connection.send(data)
		if self.proxy:
			self.proxy.send(data)

		# connected means no need to add to pending_data_arr
		if not self._proxy_connected and not self._cb_connected:
			self._pending_data_arr.append(data)

	def connectionLost(self, reason):
		if self.cb_connection:
			self.cb_connection.close()
		if self.proxy:
			self.proxy.close()

	def _parseHTTPHeader(self):
		return None
	def respondBadRequest(self):
		log.msg('respondBadRequest')
		self.transport.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
		self.transport.loseConnection()
	def respondNotFound(self):
		log.msg('respondNotFound')
		not_found_content = '<html><head><title>not found</title></head><body><h1>not found (from connbridge)</h1></body></html>'
		self.transport.write(b"HTTP/1.1 404 Not Found\r\nContent-length:%d\r\n\r\n%s"%(len(not_found_content), not_found_content))
		self.transport.loseConnection()
	def respondGatewayTimeout(self):
		log.msg('respondGatewayTimeout')
		gateway_timeout_content = '''<html><head><title>can not connect to proxy</title></head>
		<body><h1>can not connect to proxy (from connbridge)</h1></body></html>'''
		self.transport.write(b'HTTP/1.1 504 Gateway Timeout\r\nContent-length:%d\r\n\r\n%s'
			%(len(gateway_timeout_content), gateway_timeout_content))
		self.transport.loseConnection()

	def try_cb_connect(self):
		def connect(_):
			self.factory.bridge.cb_connect(self.host, self.port, self)
			print '_pending_data_arr : ',len(self._pending_data_arr)
			for data in self._pending_data_arr:
				self.cb_connection.send(data)
		def connect_failed(x):
			self.cb_connect_failed()
			return x
		if not self.factory.bridge:
			d = self.factory.bridge_defer
			if not d:
				d = self.factory.try_create_bridge()
			d.addCallbacks(connect, connect_failed)
		else:
			connect(None)

	def proxy_connected(self):
		log.msg('proxy_connected')
		self._proxy_connected = True
		print len(self._pending_data_arr)
		for data in self._pending_data_arr:
			self.proxy.send(data)
		if self.auto_proxy:
			self.factory.update_go_bridge_info(self.host, False)
			assert self.failed_count < 2
			if self.cb_connection:
				self.cb_connection.close()
			if self.delayed_call:
				c, self.delayed_call = self.delayed_call, None
				c.cancel()
	def proxy_data_received(self, data):
		self.transport.write(data)
	def proxy_connection_lost(self, reason):
		self.transport.loseConnection()
	def proxy_connect_failed(self, reason):
		log.msg('proxy_connect_failed auto_proxy:%s initial_go_bridge:%s failed_count:%s'
				% (self.auto_proxy, self.initial_go_bridge, self.failed_count))
		if self.auto_proxy:
			if self.initial_go_bridge is False:
				log.msg('direct failed, try bridge')
				assert self.failed_count == 0
				self.try_cb_connect()
			elif self.initial_go_bridge is True:
				assert self.failed_count == 1
				self.respondNotFound()
			else:
				assert self.initial_go_bridge is None
				assert self.failed_count < 2
				if self.failed_count == 0:
					pass # still trying bridge
				else:
					assert self.failed_count == 1
					self.respondNotFound()
		else:
			self.respondNotFound()
		self.failed_count += 1

	def cb_connected(self):
		log.msg('cb_connected')
		self._cb_connected = True
		if self.auto_proxy:
			self.factory.update_go_bridge_info(self.host, True)
			if self.proxy:
				self.proxy.close()
	def cb_data_received(self, data):
		self.transport.write(data)
	def cb_connection_lost(self):
		log.msg('cb_connection_lost')
		self.transport.loseConnection()
	def cb_connect_failed(self):
		log.msg('cb_connect_failed auto_proxy:%s initial_go_bridge:%s failed_count:%s'
				% (self.auto_proxy, self.initial_go_bridge, self.failed_count))
		if self.auto_proxy:
			if self.initial_go_bridge is True:
				log.msg('bridge failed, try direct')
				assert self.failed_count == 0
				proxy_connect(self.host, self.port, self)
			elif self.initial_go_bridge is False:
				assert self.failed_count == 1
				self.respondNotFound()
			else:
				assert self.initial_go_bridge is None
				assert self.failed_count < 2
				if self.failed_count == 0:
					pass # still trying direct
				else:
					assert self.failed_count == 1
					self.respondNotFound()
		else:
			self.respondNotFound()
		self.failed_count += 1

class LocalServerFactory(Factory):
	protocol = LocalServer
	(AUTO, DIRECT, BRIDGE) = range(1,1+3)
	def __init__(self):
		self.mode = self.AUTO
		#self.mode = self.BRIDGE
		self.bridge = None
		self.pac = PACList()
		self.auto_map = {}
		self.bridge_defer = None
		d = self.try_create_bridge()
		assert self.bridge_defer == d
	def try_create_bridge(self):
		log.msg('try_create_bridge')
		from twisted.internet import reactor
		self.bridge_factory = BridgeClientFactory(self, True)
		self.bridge_factory.protocol = SafeBridgeClient
		remote_addr = '23.88.59.196'
		#remote_addr = '127.0.0.1'
		reactor.connectTCP(remote_addr, remote_server.PORT, self.bridge_factory)
		self.bridge_defer = defer.Deferred()
		return self.bridge_defer
	def bridge_created(self, bridge):
		assert not self.bridge and bridge
		self.bridge = bridge
		log.msg('bridge created')
		d, self.bridge_defer = self.bridge_defer, None
		d.callback(bridge)
	def bridge_lost(self):
		log.msg('bridge lost')
		self.bridge = None
	def bridge_create_failed(self):
		log.msg('bridge create failed')
		d, self.bridge_defer = self.bridge_defer, None
		d.errback(Exception('bridge create failed'))
	def should_go_bridge(self, host):
		return self.auto_map.get(host)
	def update_go_bridge_info(self, host, should_go_bridge):
		self.auto_map[host] = should_go_bridge

class PACList():
	def should_go_bridge(self, host):
		return False
		#return True

def start_local_server():
	from twisted.internet import reactor
	f = LocalServerFactory()
	reactor.listenTCP(PORT, f)

def main():
	log.startLogging(sys.stdout)
	from twisted.internet import reactor
	start_local_server()
	isMainThread = threading.current_thread().name == 'MainThread'
	log.msg('isMainThread : %s'%isMainThread)
	reactor.run(installSignalHandlers=isMainThread)

if __name__ == '__main__':
	main()