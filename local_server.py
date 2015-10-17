from twisted.internet.protocol import Protocol,Factory,ClientFactory
from twisted.protocols import basic
import remote_server
from wpprotocol import WPClientFactory
import sys
from twisted.python import log
from twisted.internet import defer

PORT = 8585

class LocalServer(basic.LineReceiver):
	def __init__(self):
		self._first_line_received = False
		self._headers = {}
		self._header_lines = []
		self._go_proxy = False
		self.forwarder = None
		self._pending_data_arr = []

	def lineReceived(self, line):
		self._header_lines.append(line)
		if not line:
			if not self._first_line_received or not 'host' in self._headers:
				self.respondBadRequest()
				return
			host = self._headers['host']
			port = 80
			if ':' in self._request:
				_, port_str = self._request.rsplit(':', 1)
				i = 0
				while i < len(port_str) and port_str[i].isdigit():
					i += 1
				if i != 0:
					port = int(port_str[:i])
			if ':' in host:
				host,port_str = host.split(':', 1)
				if not port_str.isdigit():
					self.respondBadRequest()
					return
				port = int(port_str)
			#avoid infinite loop
			if port == PORT:
				self.respondBadRequest()
				return
			self._go_proxy = self.factory.pac.should_go_proxy(host)
			if self._go_proxy:
				if not self.factory.link:
					self.respondGatewayTimeout()
					return
				d = defer.maybeDeferred(self.factory.link.create_connection, host, port)
			else:
				f = DirectForwarderFactory()
				from twisted.internet import reactor
				reactor.connectTCP(host, port, f)
				d = f.getDirectForwader()
			d.addCallbacks(self.forwarder_created, self.forwarder_create_failed)

			self.setRawMode()
		elif not self._first_line_received:
			parts = line.split()
			if len(parts) != 3:
				self.respondBadRequest()
				return
			self._command, self._request, self._version = parts
			self._first_line_received = True
			log.msg(line)
		else:
			header, data = line.split(b':', 1)
			header = header.lower()
			data = data.strip()
			self._headers[header] = data

	def rawDataReceived(self, data):
		if self.forwarder:
			self.forwarder.send(data)
		else:
			self._pending_data_arr.append(data)
		
	def connectionLost(self, reason):
		forwarder = self.forwarder
		if forwarder:
			self._clear_forwarder()
			forwarder.close()

	def _parseHTTPHeader(self):
		return None
	def respondBadRequest(self):
		log.msg('respondBadRequest')
		self.transport.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
		self.transport.loseConnection()
	def respondNotFound(self):
		log.msg('respondNotFound')
		not_found_content = '<html><head><title>not found</title></head><body><h1>not found</h1></body></html>'
		self.transport.write(b"HTTP/1.1 404 Not Found\r\nContent-length:%d\r\n\r\n%s"%(len(not_found_content), not_found_content))
		self.transport.loseConnection()
	def respondGatewayTimeout(self):
		log.msg('respondGatewayTimeout')
		self.transport.write(b'HTTP/1.1 504 Gateway Timeout\r\n\r\n')
		self.transport.loseConnection()

	def forward_data_received(self, data):
		self.transport.write(data)
	def forwarder_closed(self):
		log.msg('forwarder closed')
		self._clear_forwarder()
		self.transport.loseConnection()
	def forwarder_created(self, forwarder):
		print 'forwarder created'
		self.forwarder = forwarder
		self.forwarder.set_callbacks(self.forward_data_received, self.forwarder_closed)
		if self._command != 'CONNECT':
			#add a new line
			self._header_lines.append('')
			print self._header_lines
			self._pending_data_arr.append('\r\n'.join(self._header_lines))
		else:
			self.transport.write('HTTP/1.1 200 OK\r\n\r\n')
		for data in self._pending_data_arr:
			self.forwarder.send(data)
	def forwarder_create_failed(self, reason):
		log.msg('forwarder create failed : %s', str(reason))
		self.respondNotFound()

	def _clear_forwarder(self):
		self.forwarder.set_callbacks(None, None)
		self.forwarder = None

class LocalServerFactory(Factory):
	protocol = LocalServer
	def __init__(self):
		self.link = None
		self.pac = PACList()
		from twisted.internet import reactor
		self.link_factory = WPClientFactory(self, True)
		#remote_addr = '23.88.59.196'
		remote_addr = '127.0.0.1'
		reactor.connectTCP(remote_addr, remote_server.PORT, self.link_factory)
	def link_created(self, link):
		assert not self.link and link
		self.link = link
		log.msg('link created')
	def link_lost(self):
		self.link = None
	def link_create_failed(self):
		pass

class DirectForwarder(Protocol):
	def __init__(self):
		self.data_received_callback = None
		self.closed_callback = None
	# Forwarder
	def set_callbacks(data_received_callback, closed_callback):
		self.data_received_callback = data_received_callback
		self.closed_callback = closed_callback
	def send(self, data):
		self.transport.write(data)
	def close(self):
		self.loseConnection()
	# Protocol
	def dataReceived(self, data):
		if self.data_received_callback:
			self.data_received_callback(data)
	def connectionLost(self, reason):
		if self.closed_callback:
			self.closed_callback()
	def connectionMade(self):
		d, self.factory.deferred.callback = self.factory.deferred.callback, None
		d.callback(self)

class DirectForwarderFactory(ClientFactory):
	protocol = DirectForwarder
	def __init__(self):
		self.deferred = defer.Deferred()
	def getDirectForwader():
		return self.deferred
	def clientConnectionFailed(self, connector, reason):
		d, self.deferred = self.deferred, None
		d.errback(reason)

class PACList():
	def should_go_proxy(self, host):
		#return False
		return True

def start_local_server():
	from twisted.internet import reactor
	f = LocalServerFactory()
	reactor.listenTCP(PORT, f)

def main():
	from twisted.internet import reactor
	start_local_server()
	reactor.run()

if __name__ == '__main__':
	log.startLogging(sys.stdout)
	main()