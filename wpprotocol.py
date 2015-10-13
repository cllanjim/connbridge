
import struct, random
from twisted.internet.protocol import Protocol, Factory, ClientFactory
from twisted.internet import defer
import user_manager
from forwarder import WPClientForwarderManager, WPServerForwarderManager
from twisted.python import log

#wall proxy portocol

# commands
# response

class COMMAND:
	MIN = 1
	MAX = 6
	[LOGIN, CONNECT, SEND, CLOSE_CONNECTION, CLOSE_LINK] = range(MIN, MAX)

OK_RESPONSE = 'ok'

class WPProtocol(Protocol):
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

	def send_data(self, connection_id, data):
		data_len = len(data)
		if data_len <= self.max_arg_size:
			self.send_command(COMMAND.SEND, str(connection_id), data)
			return
		start_offset = 0
		while start_offset < data_len:
			self.send_command(COMMAND.SEND, str(connection_id), data[start_offset:start_offset + self.max_arg_size])
			start_offset += self.max_arg_size

	def close_connection(self, connection_id):
		self.send_command(COMMAND.CLOSE_CONNECTION, str(connection_id))

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
			short_arg = arg if len(arg) < 86 else arg[:80] + '......' 
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
				print data_offset, arg_str_length, data_len, args
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
			self.forwarder_manager.send_data_to_forwarder(id, data)
		elif cmd == COMMAND.CLOSE_CONNECTION:
			if len(args) != 1:
				self.closeLinkWithMsg('CLOSE_CONNECTION expect 2 args')
				return
			id = args[0]
			if not id.isdigit():
				self.closeLinkWithMsg('CLOSE_CONNECTION expect integer id')
				return
			id = int(id)
			self.forwarder_manager.close_forwarder(id)
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

class WPClientProtocol(WPProtocol):
	def __init__(self):
		WPProtocol.__init__(self)
		self._logined = False
		self.forwarder_manager = WPClientForwarderManager(self)

	def connectionMade(self):
		self.key = random.randint(1,255)
		self.transport.write(struct.pack('!B', self.key))
		self.login('0.1', 'hejl', '123456')

	def login(self, version, user_name, password):
		self.send_command(COMMAND.LOGIN, version, user_name, password)

	def create_connection(self, connection_id, host, port):
		assert isinstance(host, str)
		assert isinstance(port, int) and port >= 1 and port <= 65535
		self.send_command(COMMAND.CONNECT, str(connection_id), host, str(port))

	def command_received(self, cmd, args):
		if not self._logined:
			self.closeLinkWithMsg('cmds before login response received')
			return
		else:
			WPProtocol.command_received(self, cmd, args)
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

class WPServerProtocol(WPProtocol):
	def __init__(self):
		WPProtocol.__init__(self)
		self._logined = False
		self.forwarder_manager = WPServerForwarderManager(self)

	def dataReceived(self, data):
		if not self.key:
			self.key = struct.unpack('!B', data[0])[0]
			if self.key == 0:
				self.closeLinkWithMsg('key cannot be zero')
				return
			data = data[1:]
		assert self.key
		if data:
			WPProtocol.dataReceived(self, data)
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
			self.forwarder_manager.create_forwarder(id, (host, port))
		else:
			WPProtocol.command_received(self, cmd, args)

	def response_received(self, cmd, response):
		if not self._logined:
			self.closeLinkWithMsg('response before login command received')
			return

class WPClientFactory(ClientFactory):
	protocol = WPClientProtocol

	def __init__(self):
		self.deferred = defer.Deferred()

	def login_succeed(self, link):
		self.link = link
		d, self.deferred = self.deferred, None
		d.callback(link)

	def get_link(self):
		return self.deferred

class WPServerFactory(Factory):
	protocol = WPServerProtocol

def main():
	pass

def test():
	print COMMAND.LOGIN

if __name__ == '__main__':
	test()