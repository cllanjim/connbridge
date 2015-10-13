from twisted.internet.protocol import Protocol,Factory
from twisted.protocols import basic
from forwarder import ForwarderMaster, create_direct_forwarder, create_wp_forwarder
from twisted.web import http
import remote_server
from wpprotocol import WPClientFactory
import sys
from twisted.python import log

PORT = 8585

class LocalServer(basic.LineReceiver, ForwarderMaster):
	def __init__(self):
		self._first_line_received = False
		self._headers = {}
		self._header_lines = []
		self._go_proxy = False
		self.forwarder = None
		self._pending_data_arr = []

	def lineReceived(self, line):
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
				print self.factory.link
				create_wp_forwarder(self, self.factory.link.forwarder_manager, (host, port))
			else:
				create_direct_forwarder(self, (host,port))

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
		self._header_lines.append(line)

	def rawDataReceived(self, data):
		if self.forwarder:
			self.forwarder.forward_data_from_master(data)
		else:
			self._pending_data_arr.append(data)
		
	def connectionLost(self, reason):
		from twisted.internet import reactor
	def _parseHTTPHeader(self):
		return None
	def respondBadRequest(self):
		self.transport.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
		self.transport.loseConnection()
	def respondNotFound(self):
		not_found_content = '<html><head><title>not found</title></head><body><h1>not found</h1></body></html>'
		self.transport.write(b"HTTP/1.1 404 Not Found\r\nContent-length:%d\r\n\r\n%s"%(len(not_found_content), not_found_content))
		self.transport.loseConnection()

	def forward_data_received(self, data):
		self.transport.write(data)
	def forwarder_closed(self, reason):
		log.msg('forwarder closed : %s' % str(reason))
		self.transport.loseConnection()
	def forwarder_created(self, forwarder):
		print 'LocalServer forwarder created'
		self.forwarder = forwarder
		if self._command != 'CONNECT':
			self._pending_data_arr.append('\r\n'.join(self._header_lines))
			self._pending_data_arr.append('\r\n')
		else:
			self.transport.write('HTTP/1.1 200 OK\r\n\r\n')
		for pending_data in self._pending_data_arr:
			self.forwarder.forward_data_from_master(pending_data)
	def forwarder_create_failed(self, reason):
		self.respondNotFound()

class LocalServerFactory(Factory):
	protocol = LocalServer
	def __init__(self):
		self.link = None
		self.pac = PACList()
	def set_link(self, link):
		assert not self.link and link
		self.link = link
		log.msg('link created')

class PACList():
	def should_go_proxy(self, host):
		#return False
		return True

def start_local_server():
	from twisted.internet import reactor
	f = LocalServerFactory()
	reactor.listenTCP(PORT, f)
	d = create_wp_link()
	d.addCallback(lambda link:f.set_link(link))
	#d.addErrback(lambda )

def create_wp_link():
	from twisted.internet import reactor
	f = WPClientFactory()
	reactor.connectTCP('23.88.59.196', remote_server.PORT, f)
	return f.get_link()

def main():
	from twisted.internet import reactor
	start_local_server()
	reactor.run()

if __name__ == '__main__':
	log.startLogging(sys.stdout)
	main()