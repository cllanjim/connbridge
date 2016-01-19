from twisted.internet.protocol import Protocol, ClientFactory

class ProxyProctocl(Protocol):
	def dataReceived(self, data):
		self.factory.client.proxy_data_received(data)
	def connectionLost(self, reason):
		self.factory.client.proxy_connection_lost(reason)
	def connectionMade(self):
		self.factory.proxy_protocol = self
		self.factory.client.proxy_connected(reason)

class ProxyFactory(ClientFactory):
	protocol = ProxyProctocl
	def __init__(self, client):
		self.client = client
		client.set_proxy(self)
		self.proxy_protocol = None
		self.connector = None
	def startedConnecting(self, connector):
		self.connector = connector
	def clientConnectionFailed(self, connector, reason):
		self.client.proxy_connect_failed(reason)
	def disconnect(self):
		if self.proxy_protocol:
			self.proxy_protocol.transport.loseConnection()
		elif self.connector:
			self.connector.stopConnecting()
		else:
			pass
	def send_data(self, data):
		self.proxy_protocol.transport.write(data)

class ProxyClient:
	def __init__(self):
		self.proxy = None
		self.proxy_closed = False
		self.connected = False
		self._send_buffer = []

	def proxy_connect(self, host, port):
		self.connected = False
		self.closed = False
		factory = ProxyFactory(client)
		self.proxy = factory
		reactor.connectTCP(host, port, factory)
	def proxy_close(self):
		if not self.proxy_closed:
			self.proxy.disconnect()
			self.proxy = None
			self._send_buffer = None
	def proxy_send_data(self, data):
		if not self.connected:
			self._send_buffer.append(data)
			return
		self.proxy.send_data(data)

	# callbacks
	def proxy_connected(self):
		self.connected = True
		for data in self._send_buffer:
			self.proxy.send_data(data)
	def proxy_data_received(self, data):
		pass
	def proxy_connection_lost(self, reason):
		pass
	def proxy_connect_failed(self, reason):
		pass
