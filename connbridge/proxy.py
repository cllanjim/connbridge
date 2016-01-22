from twisted.internet.protocol import Protocol, ClientFactory
from twisted.python import log

class ProxyProctocl(Protocol):
	def dataReceived(self, data):
		self.factory.client.proxy_data_received(data)
	def connectionLost(self, reason):
		self.factory.protocol_closed(reason)
	def connectionMade(self):
		log.msg('proxy connectionMade')
		self.factory.protocol_connected(self)

class ProxyFactory(ClientFactory):
	protocol = ProxyProctocl
	def __init__(self, client):
		self.client = client
		client.proxy = self
		self.closed = False
		self._send_buffer = []
		self.proxy_protocol = None
		self.connector = None
	def startedConnecting(self, connector):
		self.connector = connector
	def clientConnectionFailed(self, connector, reason):
		if not self.closed:
			self.closed = True
			self.client.proxy_connect_failed(reason.value)

 	def protocol_closed(self, reason):
 		if not self.closed:
			self.closed = True
			self.client.proxy_connection_lost(reason)

	def protocol_connected(self, proxy_protocol):
		self.proxy_protocol = proxy_protocol
		for data in self._send_buffer:
			self.proxy_protocol.transport.write(data)

	# proxy
	def send(self, data):
		if self.proxy_protocol:
			self.proxy_protocol.transport.write(data)
		else:
			self._send_buffer.append(data)
	def close(self): 
		if not self.closed:
			self.closed = True
			if self.proxy_protocol:
				self.proxy_protocol.transport.loseConnection()
			elif self.connector:
				self.connector.stopConnecting()
			else:
				pass

def proxy_connect(host, port ,client):
	from twisted.internet import reactor
	factory = ProxyFactory(client)
	client.proxy = factory
	reactor.connectTCP(host, port, factory)

class ProxyClient:
	def __init__(self):
		self.proxy = None

	# callbacks
	def proxy_connected(self):
		pass
	def proxy_data_received(self, data):
		pass
	def proxy_connection_lost(self, reason):
		pass
	def proxy_connect_failed(self, reason):
		pass
