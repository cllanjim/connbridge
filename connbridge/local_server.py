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

class LocalServer(basic.LineReceiver, ProxyClient, CBConnectionClient):
	def __init__(self):
		ProxyClient.__init__(self)
		CBConnectionClient.__init__(self)
		self._first_line_received = False
		self._headers = {}
		self._header_lines = []
		self._go_bridge = False
		self._pending_data_arr = []
		self.auto_proxy = False
		self.dest_host = None
		self.dest_port = None
		self.auto_retried = False

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
			self._go_bridge = mode == self.factory.BRIDGE or (auto_proxy and self.factory.should_go_bridge(host))
			log.msg('%s %d go_proxy:%s auto_proxy:%d'%(host, port, self._go_bridge, auto_proxy))
			self.host = host
			self.port = port
			self.auto_proxy = auto_proxy
			if self._go_bridge:
				self.try_cb_connect()
			else:
				proxy_connect(host, port ,self)

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
		if self.cb_connection:
			self.cb_connection.send(data)
		elif self.proxy:
			self.proxy.send(data)
		else:
			self._pending_data_arr.append(data)
		
	def connectionLost(self, reason):
		if self.cb_connection:
			self.cb_connection.close()
		elif self.proxy:
			self.proxy.close()
		else:
			pass
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
			for data in self._pending_data_arr:
				self.cb_connection.send(data)
		if not self.factory.bridge:
			d = self.factory.bridge_defer
			if not d:
				d = self.factory.try_create_bridge()
			d.addCallbacks(connect, lambda x:self.respondGatewayTimeout())
		else:
			connect(None)

	def proxy_connected(self):
		log.msg('proxy_connected')
		for data in self._pending_data_arr:
			self.proxy.send(data)
		if self.auto_proxy:
			self.factory.update_go_bridge_info(self.host, False)
	def proxy_data_received(self, data):
		self.transport.write(data)
	def proxy_connection_lost(self, reason):
		self.transport.loseConnection()
	def proxy_connect_failed(self, reason):
		if self.auto_proxy and not self.auto_retried:
			log.msg('direct failed, try bridge')
			self.auto_retried = True
			self.try_cb_connect()
		else:
			self.respondNotFound()

	def cb_connected(self):
		log.msg('cb_connected')
		if self.auto_proxy:
			self.factory.update_go_bridge_info(self.host, True)
	def cb_data_received(self, data):
		self.transport.write(data)
	def cb_connection_lost(self):
		log.msg('cb_connection_lost')
		self.transport.loseConnection()
	def cb_connect_failed(self):
		if self.auto_proxy and not self.auto_retried:
			log.msg('bridge failed, try direct')
			self.auto_retried = True
			proxy_connect(self.host, self.port, self)
		else:
			log.msg('cb_connect_failed')
			self.respondNotFound()

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
		return self.auto_map.get(host, False)
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