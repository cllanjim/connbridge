from twisted.internet.protocol import Protocol,Factory,ClientFactory
from twisted.protocols import basic
import remote_server
from cbprotocol import CBClientFactory
import sys,threading
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
					print host_header
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

			self._go_proxy = self.factory.pac.should_go_proxy(host)
			if self._go_proxy:
				if not self.factory.link:
					self.respondGatewayTimeout()
					return
				d = defer.maybeDeferred(self.factory.link.create_connection, host, port)
			else:
				f = DirectForwarderFactory()
				from twisted.internet import reactor
				log.msg('%s %d'%(host, port))
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
		log.msg('forwarder created')
		self.forwarder = forwarder
		self.forwarder.set_callbacks(self.forward_data_received, self.forwarder_closed)

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
		self.link_factory = CBClientFactory(self, True)
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
	def __init__(self, id):
		self.data_received_callback = None
		self.closed_callback = None
		self.id = id
		
	# Forwarder
	def set_callbacks(self, data_received_callback, closed_callback):
		self.data_received_callback = data_received_callback
		self.closed_callback = closed_callback
	def send(self, data):
		log.msg('DirectForwarder.send %d %s(%d)'%(self.id, repr(data[:30]), len(data)))
		self.transport.write(data)
	def close(self):
		self.transport.loseConnection()
	# Protocol
	def dataReceived(self, data):
		log.msg('DirectForwarder.dataReceived %d %s(%d)'%(self.id, repr(data[:30]), len(data)))
		if self.data_received_callback:
			self.data_received_callback(data)
		else:
			log.msg('DirectForwarder.dataReceived %d without callback' % self.id)
	def connectionLost(self, reason):
		log.msg('DirectForwarder.connectionLost %d'%self.id)
		if self.closed_callback:
			self.closed_callback()
	def connectionMade(self):
		d, self.factory.deferred = self.factory.deferred, None
		d.callback(self)

class DirectForwarderFactory(ClientFactory):
	id = 1
	def __init__(self):
		self.deferred = defer.Deferred()
	def buildProtocol(self, addr):
		print 'buildProtocol'
		p = DirectForwarder(self.__class__.id)
		p.factory = self
		self.__class__.id += 1
		print self.__class__.id
		return p
	def getDirectForwader(self):
		return self.deferred
	def clientConnectionFailed(self, connector, reason):
		log.msg('DirectForwarderFactory.clientConnectionFailed')
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
	log.startLogging(sys.stdout)
	from twisted.internet import reactor
	start_local_server()
	isMainThread = threading.current_thread().name == 'MainThread'
	log.msg('isMainThread : %s'%isMainThread)
	reactor.run(installSignalHandlers=isMainThread)

if __name__ == '__main__':
	main()