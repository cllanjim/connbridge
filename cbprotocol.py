
import struct, random
from twisted.internet.protocol import Protocol, Factory, ClientFactory
from twisted.internet import defer
import user_manager
from twisted.python import log

#wall proxy portocol

# commands
# response

class COMMAND:
	MIN = 1
	MAX = 6
	[LOGIN, CONNECT, SEND, CLOSE_CONNECTION, CLOSE_LINK] = range(MIN, MAX)

OK_RESPONSE = 'ok'

class CBProtocol(Protocol):
	'''
	wall proxy protocol

	frame format : frame size(4 byte unsigned int), payload

	'''
	max_arg_size = 0x10000-1 #2^16-1

	def __init__(self):
		self.key = None
		self._frame_size = None
		self._received_data_arr = []
		self._received_data_len = 0
		self._connections = {}
		self._next_connection_id = 1

	def send_data(self, connection_id, data):
		data_len = len(data)
		if data_len <= self.max_arg_size:
			self.send_command(COMMAND.SEND, str(connection_id), data)
			return
		start_offset = 0
		while start_offset < data_len:
			self.send_command(COMMAND.SEND, str(connection_id), data[start_offset:start_offset + self.max_arg_size])
			start_offset += self.max_arg_size

	def _encode(self, data):
		byte_arr = []
		for c in data:
			byte_arr.append(chr(ord(c) ^ self.key))
		return ''.join(byte_arr)

	def _decode(self, data):
		return self._encode(data)

	def _pack_str(self, s):
		assert len(s) <= self.max_arg_size
		assert isinstance(s, str)
		data = struct.pack('!H', len(s)) + s
		return data

	def _format_byte_arr(self, byte_arr):
		msg = []
		for byte in byte_arr:
			msg.append(str(ord(byte)))
		return ' '.join(msg)

	def _short_command(self, command, args):
		short_args = []
		for arg in args[:5]:
			short_arg = arg if len(arg) < 86 else arg[:80] + '......(%d bytes)' % len(arg)
			short_args.append(short_arg)
		return '%d %s' % (command, short_args)

	def send_frame(self, data_arr):
		frame_size = 4
		for data in data_arr:
			frame_size += len(data)
		self.transport.write(self._encode(struct.pack('!I', frame_size)))
		for data in data_arr:
			self.transport.write(self._encode(data))

	def send_command(self, command, *args):
		assert len(args) < 256
		log.msg('> %s'%self._short_command(command, args))
		data_arr = [struct.pack('!b', command), struct.pack('!B', len(args))]
		for arg in args:
			data_arr.append(self._pack_str(arg))
		self.send_frame(data_arr)

	def send_response(self, command, response_msg):
		return self.send_command(-command, response_msg)

	def send_ok_response(self, command):
		return self.send_response(command, OK_RESPONSE)

	def dataReceived(self, data):
		data = self._decode(data)
		self._received_data_arr.append(data)
		self._received_data_len += len(data)
		self.update_frame_receiving_state()

	def update_frame_receiving_state(self):
		while self._received_data_arr:
			if self._frame_size is None:
				if self._received_data_len < 4:
					return
				frame_size_str = ''
				for data in self._received_data_arr:
					frame_size_str += data[:4-len(frame_size_str)]
					if len(frame_size_str) == 4:
						break
				assert len(frame_size_str) == 4
				self._frame_size = struct.unpack('!I', frame_size_str)[0]
				if self._frame_size <= 4:
					self._frame_size = None
					self.closeLinkWithMsg('invalide frame size : %d'%self._frame_size)
					return
			assert self._frame_size
			if self._frame_size > self._received_data_len:
				return
			#frame data ready
			frame_data_arr = []
			to_read_len = self._frame_size
			new_recived_data_arr = []
			for data in self._received_data_arr:
				if not to_read_len:
					new_recived_data_arr.append(data)
				elif len(data) <= to_read_len:
					frame_data_arr.append(data)
					to_read_len -= len(data)
				else:
					frame_data_arr.append(data[:to_read_len])
					new_recived_data_arr.append(data[to_read_len:])
					to_read_len = 0
			new_recived_data_len = 0
			for data in new_recived_data_arr:
				new_recived_data_len += len(data)
			assert not to_read_len
			assert new_recived_data_len + self._frame_size == self._received_data_len
			self._received_data_arr = new_recived_data_arr
			self._received_data_len = new_recived_data_len
			#remove 4 byte of frame size
			if len(frame_data_arr[0]) > 4:
				frame_data_arr[0] = frame_data_arr[0][4:]
			else:
				new_frame_data_arr = []
				start_data_index = 0
				start_data_offset = 0
				to_remove_len = 4
				for i,data in enumerate(frame_data_arr):
					if not to_remove_len:
						new_frame_data_arr.append(data)
					elif len(data) <= to_remove_len:
						to_remove_len -= len(data)
					else:
						new_frame_data_arr.append(data[to_remove_len:])
						to_remove_len = 0
				new_frame_data_len = 0
				for data in new_frame_data_arr:
					new_frame_data_len += len(data)
				assert new_frame_data_len + 4 == self._frame_size
				frame_data_arr = new_frame_data_arr
			#notify frame received
			self.frameReceived(''.join(frame_data_arr))
			self._frame_size = None

	def frameReceived(self, data):
		data_len = len(data)
		if data_len < 2:
			self.closeLinkWithMsg('invalid frame size : %d'% data_len)
			return
		t = struct.unpack('!b', data[0])[0]
		arg_count = struct.unpack('!B', data[1])[0]
		data_offset = 2
		args = []
		for i in range(arg_count):
			#2 byte for arg length
			if data_offset + 2 > data_len:
				log.msg('%d,%d, %s'%(data_offset, data_len, str(args)))
				self.closeLinkWithMsg('invalid command : args count not match (%d/%d)'%(i, arg_count))
				return
			arg_str_length = struct.unpack('!H', data[data_offset:data_offset+2])[0]
			if data_offset + 2 + arg_str_length > data_len:
				log.msg('%d,%d,%d,%s'%(data_offset, arg_str_length, data_len, str(args)))
				self.closeLinkWithMsg('invalid command : args count not match (%d/%d)'%(i, arg_count))
				return
			arg = data[data_offset+2: data_offset+2+arg_str_length]
			data_offset += 2+arg_str_length
			args.append(arg)
		if data_offset != data_len:
			self.closeLinkWithMsg('invalid command : more data than needed')
			return
		log.msg('< %s'%self._short_command(t,args))
		cmd = abs(t)
		if cmd < COMMAND.MIN or cmd > COMMAND.MAX:
			self.closeLinkWithMsg('invalid cmd : %d'%cmd)
			return
		if t < 0:
			if len(args) != 1:
				self.closeLinkWithMsg('invalide response : only one arg needed, passed %d'%len(args))
				return
			self.response_received(cmd, args[0])
		else:
			self.command_received(cmd, args)

	def command_received(self,cmd, args):
		if cmd == COMMAND.SEND:
			if len(args) != 2:
				self.closeLinkWithMsg('SEND expect 2 args')
				return
			id = args[0]
			if not id.isdigit():
				self.closeLinkWithMsg('SEND expect integer id')
				return
			id = int(id)
			data = args[1]
			if id >= self._next_connection_id:
				self.closeLinkWithMsg('SEND invalid connection id')
				return
			# Maybe data to closed connection, just ignore it
			if id not in self._connections:
				log.msg('SEND outdated id : %d' % id)
				return
			connection = self._connections[id]
			connection._data_received(data)
		elif cmd == COMMAND.CLOSE_CONNECTION:
			if len(args) != 1:
				self.closeLinkWithMsg('CLOSE_CONNECTION expect 1 args')
				return
			id = args[0]
			if not id.isdigit():
				self.closeLinkWithMsg('CLOSE_CONNECTION expect integer id')
				return
			id = int(id)
			if id >= self._next_connection_id:
				self.closeLinkWithMsg('CLOSE_CONNECTION invalid connection id')
				return
			# Maybe to closed connection, just ignore it
			if id not in self._connections:
				log.msg('CLOSE_CONNECTION outdated id : %d' % id)
				return
			connection = self._connections[id]
			self._connections.pop(id)
			connection._close()
		elif cmd == COMMAND.CLOSE_LINK:
			if len(args) != 1:
				self.closeLinkWithMsg('CLOSE_LINK expect 1 arg, given %d'%len(args))
				return
			msg = args[0]
			log.msg('close link : %s' % msg)
			self.transport.loseConnection()
		else:
			self.closeLinkWithMsg("invalid command : %d" % cmd)

	def response_received(self,cmd, response):
		raise NotImplementedError();

	def closeLinkWithMsg(self, msg):
		log.msg('closeLinkWithMsg : %s'% msg)
		self.send_command(COMMAND.CLOSE_LINK, msg)
		self.transport.loseConnection()
		raise Exception()

	def connectionLost(self, reason):
		for id, connection in self._connections.iteritems():
			connection._close()
		self._connections.clear()

	def close_connection(self, id):
		self.send_command(COMMAND.CLOSE_CONNECTION, str(id))
		self._connections.pop(id)

class CBClientProtocol(CBProtocol):
	def __init__(self):
		CBProtocol.__init__(self)
		self._logined = False

	def connectionMade(self):
		self.key = random.randint(1,255)
		self.transport.write(struct.pack('!B', self.key))
		self.login('0.1', 'hejl', '123456')

	def login(self, version, user_name, password):
		self.send_command(COMMAND.LOGIN, version, user_name, password)

	def command_received(self, cmd, args):
		if not self._logined:
			self.closeLinkWithMsg('cmds before login response received')
			return
		else:
			CBProtocol.command_received(self, cmd, args)
	def response_received(self, cmd, response):
		if not self._logined:
			if cmd != COMMAND.LOGIN:
				self.closeLinkWithMsg('response not for login')
				return
			if response != OK_RESPONSE:
				self.closeLinkWithMsg('response error : %s' % response)
				return
			self._logined = True
			log.msg('login succeed')
			self.factory.login_succeed(self)

	def create_connection(self, host, port):
		assert isinstance(host, str)
		assert isinstance(port, int) and port >= 1 and port <= 65535
		id = self._next_connection_id
		self.send_command(COMMAND.CONNECT, str(id), host, str(port))
		connection = CBConnection(self, id)
		self._connections[id] = connection
		self._next_connection_id += 1
		return connection

class CBServerProtocol(CBProtocol):
	def __init__(self):
		CBProtocol.__init__(self)
		self._logined = False

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
	def command_received(self, cmd, args):
		if not self._logined:
			if cmd != COMMAND.LOGIN:
				self.closeLinkWithMsg('first login please')
				return
			if len(args) != 3:
				self.closeLinkWithMsg('invalid login command')
				return
			version, username, password = args
			if version != '0.1':
				self.closeLinkWithMsg('invalid version')
				return
			if not user_manager.login(username, password):
				self.closeLinkWithMsg('invalid user name or password')
				return
			self.send_ok_response(COMMAND.LOGIN)
			self._logined = True
		elif cmd == COMMAND.CONNECT:
			if len(args) != 3:
				self.closeLinkWithMsg('CONNECT command needs 3 args, received %d'%len(args))
				return
			id, host, port = args
			if not id.isdigit() or not port.isdigit():
				self.closeLinkWithMsg('CONNECT command id and port must be integer, received %s %s'%id, port)
				return
			id = int(id)
			port = int(port)
			if id != self._next_connection_id:
				self.closeLinkWithMsg('CONNECT command id must one larger per connection')
				return
			self._next_connection_id += 1
			connection = CBServerConnection(self, id, host, port)
			self._connections[id] = connection
		else:
			CBProtocol.command_received(self, cmd, args)

	def response_received(self, cmd, response):
		if not self._logined:
			self.closeLinkWithMsg('response before login command received')
			return

class CBClientFactory(ClientFactory):
	protocol = CBClientProtocol
	MAX_RETRY_COUNT = 3

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
		if self._retry_count == 1:
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

class CBConnection():
	def __init__(self, link, id):
		self.link = link
		self.id = id
		self.data_received_callback = None
		self.closed_callback = None
		self._closed = False

	def send(self, data):
		self.link.send_data(self.id, data)

	def close(self):
		self.link.close_connection(self.id)
		self._close()

	def set_callbacks(self, data_received_callback, closed_callback):
		self.data_received_callback = data_received_callback
		self.closed_callback = closed_callback

	#called from link
	def _data_received(self, data):
		assert self.data_received_callback
		self.data_received_callback(data)

	def _close(self):
		assert not self._closed
		self._closed = True
		if self.closed_callback:
			self.closed_callback()

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