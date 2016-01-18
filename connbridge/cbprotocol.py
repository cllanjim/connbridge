
import struct, random
from twisted.internet.protocol import Protocol, Factory, ClientFactory
from twisted.internet import defer
import user_manager
from twisted.python import log
from cbprotocolbase import CBClientBase, CBServerBase

class CBProtocol(Protocol):
	'''
	wall proxy protocol

	frame format : frame size(4 byte unsigned int), payload

	'''
	max_arg_size = 0x10000 #2^16

	def __init__(self):
		self.key = None
		self._frame_size = None
		self._received_data = bytearray()
		self._connections = {}
		self._next_connection_id = 1
		self._logined = True

	def _encode(self, data):
		byte_arr = []
		for c in data:
			byte_arr.append(chr(ord(c) ^ self.key))
		return ''.join(byte_arr)

	def _decode(self, data):
		return self._encode(data)

	def send_data(self, connection_id, data):
		send_func = self.cb_send if self._is_client else self.fire_cb_data_received
		data_len = len(data)
		if data_len <= self.max_arg_size:
			send_func(connection_id, data)
			return
		start_offset = 0
		while start_offset < data_len:
			send_func(connection_id, data[start_offset:start_offset + self.max_arg_size])
			start_offset += self.max_arg_size

	def _send_msg(self, msg):
		frame_size = 4 + len(msg)
		self.transport.write(self._encode(struct.pack('!I', frame_size)))
		self.transport.write(self._encode(msg))

	def dataReceived(self, data):
		data = self._decode(data)
		self._received_data += data
		self.update_frame_receiving_state()

	def update_frame_receiving_state(self):
		while self._received_data:
			if self._frame_size is None:
				if len(self._received_data) < 4:
					return
				self._frame_size = struct.unpack_from('!I', self._received_data, 0)[0]
				if self._frame_size <= 4:
					self._frame_size = None
					self.closeLinkWithMsg('invalide frame size : %d'%self._frame_size)
					return
			assert self._frame_size
			if len(self._received_data) < self._frame_size:
				return
			#frame data ready
			frame_data = str(self._received_data[4:self._frame_size])
			self._received_data = self._received_data[self._frame_size:]
			#notify frame received
			self.frameReceived(frame_data)
			self._frame_size = None

	def frameReceived(self, data):
		try:
			self._dispatch_msg(data)
		except Exception as e:
			raise e
			self.closeLinkWithMsg(str(e))

	def closeLinkWithMsg(self, msg):
		log.msg('closeLinkWithMsg : %s'% msg)
		#self.close_link(msg)
		self.transport.loseConnection()
		raise Exception()

	def connectionLost(self, reason):
		for id, connection in self._connections.iteritems():
			connection._close()
		self._connections.clear()

	def close_connection(self, id):
		self._connections.pop(id)

	def send_data_to_connection(self, id, data):
		if id >= self._next_connection_id:
			raise Exception('SEND invalid connection id')
		# Maybe data to closed connection, just ignore it
		if id not in self._connections:
			log.msg('SEND outdated id : %d' % id)
			return
		connection = self._connections[id]
		connection._data_received(data)

class CBClientProtocol(CBProtocol, CBClientBase):
	def __init__(self):
		CBProtocol.__init__(self)
		CBClientBase.__init__(self)
		self._logined = False
		self._is_client = True

	def connectionMade(self):
		self.key = random.randint(1,255)
		self.transport.write(struct.pack('!B', self.key))
		d = self.login('0.1', 'hejl', '123456')
		def set_logined(result):
			print 'login_succeed'
			self._logined = True
			self.factory.login_succeed(self)
		d.addCallback(set_logined)

	def create_connection(self, host, port):
		assert isinstance(host, str)
		assert isinstance(port, int) and port >= 1 and port <= 65535
		id = self._next_connection_id
		self.cb_connect(id, host, port)
		connection = CBConnection(self, id)
		self._connections[id] = connection
		self._next_connection_id += 1
		return connection

	def on_cb_data_received(self, id, data):
		self.validate_logined()
		self.send_data_to_connection(id, data)

	def on_cb_connection_lost(self, id, reason):
		self.validate_logined()
		if id not in self._connections:
			return
		connection = self._connections[id]
		self._connections.pop(id)
		connection._close()

	def validate_logined(self):
		if not self._logined:
			raise Exception('cmds before login response received')

	def close_connection(self, id):
		self.cb_close(id)
		CBProtocol.close_connection(self, id)
class CBServerProtocol(CBProtocol, CBServerBase):
	def __init__(self):
		CBProtocol.__init__(self)
		CBServerBase.__init__(self)
		self._logined = False
		self._is_client = False

	def dataReceived(self, data):
		if not self.key:
			self.key = struct.unpack('!B', data[0])[0]
			if self.key == 0:
				self.closeLinkWithMsg('key cannot be zero')
				return
			data = data[1:]
		assert self.key
		if data:
			CBProtocol.dataReceived(self, data)

	def on_login(self, cmd_id, version, username, password):
		if version != '0.1':
			self.closeLinkWithMsg('invalid version')
			return
		if not user_manager.login(username, password):
			self.closeLinkWithMsg('invalid user name or password')
			return
		if self._logined:
			raise Exception('already logined')
		self.responde_login(cmd_id, True, '')
		self._logined = True

	def on_cb_connect(self, cmd_id, id, host, port):
		self.validate_logined()
		if id != self._next_connection_id:
			self.closeLinkWithMsg('CONNECT command id must one larger per connection')
			return
		self._next_connection_id += 1
		connection = CBServerConnection(self, id, host, port)
		self._connections[id] = connection
		self.responde_cb_connect(cmd_id, True, '')

	def on_cb_send(self, cmd_id, id, data):
		self.validate_logined()
		self.send_data_to_connection(id, data)
		self.responde_cb_send(cmd_id, True, '')

	def on_cb_close(self, id):
		self.validate_logined()
		if not id in self._connections:
			return
		connection = self._connections[id]
		self._connections.pop(id)
		connection._close()

	def on_close_link(self, reason):
		pass

	def response_received(self, cmd, response):
		if not self._logined:
			self.closeLinkWithMsg('response before login command received')
			return

	def validate_logined(self):
		if not self._logined:
			raise Exception('cmds before login response received')

	def close_connection(self, id):
		self.fire_cb_connection_lost(id, '')
		CBProtocol.close_connection(self, id)

class CBClientFactory(ClientFactory):
	protocol = CBClientProtocol
	MAX_RETRY_COUNT = 0

	def __init__(self, owner, auto_retry):
		self.deferred = defer.Deferred()
		self.owner = owner
		self._retry_count = 0

	def login_succeed(self, link):
		self.link = link
		self.owner.link_created(link)
		self._retry_count = 0

	def clientConnectionLost(self, connector, reason):
		log.msg('CBClientProtocol.clientConnectionLost')
		from twisted.internet import reactor
		if self._retry_count < self.MAX_RETRY_COUNT and not reactor._stopped:
			self._retry_count += 1
			log.msg('retry connect : %d' % self._retry_count)
			connector.connect()
		if self._retry_count in (0,1):
			self.owner.link_lost()

	def clientConnectionFailed(self, connector, reason):
		log.msg('CBClientProtocol.clientConnectionFailed')
		if self._retry_count < self.MAX_RETRY_COUNT:
			log.msg('retry connect : %d' % self._retry_count)
			self._retry_count += 1
			connector.connect()
		if self._retry_count == 1:
			self.owner.link_create_failed()

class CBServerFactory(Factory):
	protocol = CBServerProtocol

class CBServerConnection(CBConnection):
	def __init__(self, link, id, host, port):
		CBConnection.__init__(self, link, id)
		from twisted.internet import reactor
		reactor.connectTCP(host, port, CBResourceFetcherFactory(self))

class CBResourceFetcher(Protocol):
	'''
	fetch resource for CBServerConnection
	'''
	def connectionMade(self):
		self.factory.fetcherConnectionMade(self)

	def dataReceived(self, data):
		self.factory.fetcherDataReceived(data)

class CBResourceFetcherFactory(ClientFactory):
	protocol = CBResourceFetcher
	def __init__(self, cb_connetion):
		self.cb_connetion = cb_connetion
		self.connector = None
		self.fetcher = None
		cb_connetion.set_callbacks(self.cb_connection_data_received, self.cb_connection_closed)
		self._pending_data_arr = []

	def startedConnecting(self, connector):
		self.connector = connector

	def clientConnectionFailed(self, connector, reason):
		self.clientConnectionLost(connector, reason)

	def clientConnectionLost(self, connector, reason):
		connection = self.cb_connetion
		if connection:
			self._clear_cb_connection()
			connection.close()

	def fetcherConnectionMade(self, fetcher):
		log.msg('fetcherConnectionMade')
		self.fetcher = fetcher
		for data in self._pending_data_arr:
			log.msg('fetcher write pending data(%d)' % len(data))
			self.fetcher.transport.write(data)

	def fetcherDataReceived(self, data):
		log.msg('fetcherDataReceived')
		self.cb_connetion.send(data)

	def cb_connection_data_received(self, data):
		log.msg('cb_connection_data_received')
		if not self.fetcher:
			self._pending_data_arr.append(data)
		else:
			self.fetcher.transport.write(data)

	def cb_connection_closed(self):
		self._clear_cb_connection()
		self.connector.disconnect()

	def _clear_cb_connection(self):
		self.cb_connetion.set_callbacks(None, None)
		self.cb_connetion = None 