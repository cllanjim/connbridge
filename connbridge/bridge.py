import struct, random
from twisted.internet.protocol import Protocol, Factory, ClientFactory
from twisted.internet import defer
from twisted.python import log
from bridgebase import BridgeClientBase, BridgeServerBase
from cbconnection import CBClientConnection, CBServerConnection
import usermanager
from twisted.python import log

class UnloginException(Exception):
	pass

class LoginException(Exception):
	pass

class InvalideConnectionException(Exception):
	pass

class BridgeMixin:
	max_arg_size = 0x10000 #2^16

	def __init__(self):
		self._connections = {}
		self._next_connection_id = 1
		self._logined = True
		# for test and debug
		self.raise_exception = True

	def connectionLost(self, reason):
		log.msg('bridge connectionLost')
		for id, connection in self._connections.iteritems():
			connection.on_remote_closed()
		self._connections.clear()

	def msgReceived(self, data):
		try:
			self._base._dispatch_msg(self, data)
		except Exception as e:
			self.close_link(str(e))
			if self.raise_exception:
				raise

	def _send_msg(self, msg):
		self.sendMsg(msg)

	def cb_close(self, id):
		conn = self._connections.pop(id)
		self._base.cb_close(self, id)

	def on_cb_close(self, id):
		if not id in self._connections:
			return
		connection = self._connections.pop(id)
		connection.on_remote_closed()

	def cb_send(self, id, data):
		data_len = len(data)
		if data_len <= self.max_arg_size:
			self._base.cb_send(self, id, data)
			return
		start_offset = 0
		while start_offset < data_len:
			data_segment = data[start_offset:start_offset + self.max_arg_size]
			self._base.cb_send(self, id, data_segment)
			start_offset += self.max_arg_size

	def on_cb_send(self, id, data):
		if id >= self._next_connection_id:
			raise Exception('SEND invalid connection id')
		# Maybe data to closed connection, just ignore it
		if id not in self._connections:
			log.msg('SEND outdated id : %d' % id)
			return
		connection = self._connections[id]
		connection.on_remote_data_received(data)

	def close_link(self, reason):
		self._base.close_link(self, reason)
		self.transport.loseConnection()

	def on_close_link(self, reason):
		self.transport.loseConnection()

	def bridge_ready(self):
		pass

class BridgeClient(BridgeMixin, BridgeClientBase):
	#__metaclass__ = _AddAsInheritenceType
	_base = BridgeClientBase
	def __init__(self):
		BridgeMixin.__init__(self)
		BridgeClientBase.__init__(self)
		self._logined = False
		self._is_client = True
		self._pending_msgs = []

	def login(self, version, username, password):
		d = BridgeClientBase.login(self, version, username, password)
		d.addCallbacks(self._login_passed, self._login_failed)

	def _login_passed(self, res):
		self._logined = True
		for msg in self._pending_msgs:
			self._dispatch_msg(self._gen_msg(*msg))
		self.factory.owner.bridge_created(self)

	def _login_failed(self, res):
		self.close_link('login failed')
		self.factory.owner.bridge_create_failed()

	def cb_connect(self, host, port, client):
		assert port >= 1 and port <= 65535
		id = self._next_connection_id
		d = BridgeClientBase.cb_connect(self, id, host, port)
		conn = CBClientConnection(self, id, client)
		self._connections[id] = conn
		self._next_connection_id += 1
		client.cb_connection = conn
		def cb_connected(_):
			if conn.id in self._connections:
				conn.connected()
		def cb_connect_failed(_):
			if conn.id in self._connections:
				self._connections.pop(conn.id)
				conn.connect_failed()
		d.addCallbacks(cb_connected, cb_connect_failed)

	def dispatch_msg_hook(self, msg_type, msg_name, params):
		if not self._logined:
			self._pending_msgs.append((msg_type, msg_name, params))

	def bridge_ready(self):
		log.msg('bridge ready')
		self.login('0.1', 'hejl', '123456')

class BridgeServer(BridgeMixin, BridgeServerBase):
	#__metaclass__ = _AddAsInheritenceType
	_base = BridgeServerBase
	connection_factory = CBServerConnection
	def __init__(self, user_manager):
		BridgeMixin.__init__(self)
		BridgeServerBase.__init__(self)
		self._logined = False
		self._is_client = False
		self.user_manager = user_manager

	def on_login(self, cmd_id, version, username, password):
		try:
			if version != '0.1':
				raise LoginException('invalid version')
			if not self.user_manager.login(username, password):
				raise LoginException('invalid user name or password')
			if self._logined:
				raise LoginException('already logined')
		except LoginException as e:
			self.responde_error(cmd_id, str(e))
			raise
		self.responde_login(cmd_id)
		self._logined = True

	def on_cb_connect(self, cmd_id, id, host, port):
		if id != self._next_connection_id:
			raise InvalideConnectionException('CONNECT command id must one larger per connection')
		self._next_connection_id += 1
		connection = self.connection_factory(self, id, host, port, cmd_id)
		self._connections[id] = connection

	def dispatch_msg_hook(self, msg_type, msg_name, params):
		if not self._logined and msg_name != 'login':
			raise UnloginException()

class MessageProtocol(Protocol):
	def __init__(self):
		self._frame_size = None
		self._received_data = bytearray()

	def encode(self, data):
		return data

	def decode(self, data):
		return data

	def sendMsg(self, msg):
		msg = self.encode(msg)
		frame_size = 4 + len(msg)
		self.transport.write(struct.pack('!I', frame_size))
		self.transport.write(msg)

	def dataReceived(self, data):
		self._received_data += data
		self._update_frame_receiving_state()

	def _update_frame_receiving_state(self):
		while self._received_data:
			if self._frame_size is None:
				if len(self._received_data) < 4:
					return
				self._frame_size = struct.unpack_from('!I', buffer(self._received_data), 0)[0]
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
			frame_data = self.decode(frame_data)
			#notify frame received
			self.msgReceived(frame_data)
			self._frame_size = None

	def msgReceived(self, data):
		raise NotImplementedError()

	def connectionMade(self):
		self.bridge_ready()

class _SafeMessageProtocolMixin(MessageProtocol):
	def __init__(self):
		MessageProtocol.__init__(self)
		self.key = None

	def encode(self, data):
		byte_arr = []
		for c in data:
			byte_arr.append(chr(ord(c) ^ self.key))
		return ''.join(byte_arr)

	def decode(self, data):
		return self.encode(data)

class SafeMessageClient(_SafeMessageProtocolMixin):
	def connectionMade(self):
		self.key = random.randint(1,255)
		self.transport.write(struct.pack('!B', self.key))
		_SafeMessageProtocolMixin.connectionMade(self)

class SafeMessageServer(_SafeMessageProtocolMixin):
	def dataReceived(self, data):
		if not self.key:
			self.key = struct.unpack('!B', data[0])[0]
			if self.key == 0:
				self.loseConnection()
				return
			data = data[1:]
		assert self.key
		if data:
			MessageProtocol.dataReceived(self, data)

class DefaultBridgeClient(BridgeClient, MessageProtocol):
	def __init__(self):
		MessageProtocol.__init__(self)
		BridgeClient.__init__(self)

class DefaultBridgeServer(BridgeServer, MessageProtocol):
	def __init__(self, user_manager):
		MessageProtocol.__init__(self)
		BridgeServer.__init__(self, user_manager)

class SafeBridgeClient(BridgeClient, SafeMessageClient):
	def __init__(self):
		SafeMessageClient.__init__(self)
		BridgeClient.__init__(self)

class SafeBridgeServer(BridgeServer, SafeMessageServer):
	def __init__(self, user_manager):
		SafeMessageServer.__init__(self)
		BridgeServer.__init__(self, user_manager)

class BridgeClientFactory(ClientFactory):
	MAX_RETRY_COUNT = 0

	def __init__(self, owner, auto_retry):
		self.deferred = defer.Deferred()
		self.owner = owner
		self._retry_count = 0

	def bridge_created(self, bridge):
		self.bridge = bridge
		self.owner.bridge_created(bridge)
		self._retry_count = 0

	def clientConnectionLost(self, connector, reason):
		log.msg('CBClientProtocol.clientConnectionLost')
		from twisted.internet import reactor
		if self._retry_count < self.MAX_RETRY_COUNT and not reactor._stopped:
			self._retry_count += 1
			log.msg('retry connect : %d' % self._retry_count)
			connector.connect()
		if self._retry_count in (0,1):
			self.owner.bridge_lost()

	def clientConnectionFailed(self, connector, reason):
		log.msg('CBClientProtocol.clientConnectionFailed')
		if self._retry_count < self.MAX_RETRY_COUNT:
			log.msg('retry connect : %d' % self._retry_count)
			self._retry_count += 1
			connector.connect()
		if self._retry_count == 0 or self._retry_count == 1:
			self.owner.bridge_create_failed()

class BridgeServerFactory(Factory):
	def buildProtocol(self, addr):
		return self.protocol(usermanager.UserManager())