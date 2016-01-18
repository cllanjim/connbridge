from string import Template
import os, inspect
from bridge_def import common_commands,client_commands,server_commands

method_template = '''
	def %s(%s):
%s
'''

_file_header = '''
#don't modify this file
#this file is generated from bridge_generator.py and bridge_def.py
#don't import this file, import "bridgebase" instead

import struct
from twisted.internet import defer
from bridge_def import common_commands,client_commands,server_commands

FIRST_MSG_TYPE = 1
LAST_MSG_TYPE = 2
(MSG_TYPE_COMMAND,
	MSG_TYPE_RESPONSE,
) = range(FIRST_MSG_TYPE,LAST_MSG_TYPE+1)

def _encode(msg_type, name, params):
	assert isinstance(params, list) or isinstance(params, tuple)
	assert msg_type >= FIRST_MSG_TYPE and msg_type <= LAST_MSG_TYPE
	assert len(params) < 256
	data_arr = [struct.pack('!BB%dsB'%(len(name)), msg_type, len(name), name, len(params))]
	for param in params:
		if isinstance(param, str):
			p = struct.pack('!cI%ds'%(len(param)), 's', len(param), param)
		# bool is int, so go before int
		elif isinstance(param, bool):
			p = struct.pack('!c?', 'b', param)
		elif isinstance(param, int):
			p = struct.pack('!ci', 'i', param)
		else:
			raise Exception()
		data_arr.append(p)
	return ''.join(data_arr)

def _unpack(format, data):
	res = struct.unpack(format, data)
	assert len(res) == 1
	return res[0]

def _decode(data):
	assert isinstance(data, str)
	cur = [0]
	def next(n=1):
		ret = data[cur[0]:cur[0]+n]
		cur[0] += n
		return ret
	(msg_type, name_len) = struct.unpack('!BB', next(2))
	name = next(name_len)
	params_count = _unpack('!B', next())
	params = []
	for i in range(params_count):
		param_type = _unpack('!c', next())
		if param_type == 's':
			str_len = _unpack('!I', next(4))
			param = next(str_len)
		elif param_type == 'i':
			param = _unpack('!i', next(4))
		elif param_type == 'b':
			param = _unpack('!?', next())
		else:
			raise Exception()
		params.append(param)
	if cur[0] != len(data):
		raise Exception('too much data to decode')
	return (msg_type, name, tuple(params))

class InvalidMsgException():
	def __init__(self, reason, msg):
		self.reason = reason
		self.msg = msg
	def __str__(self):
		return '%s : %s' % (self.reason, repr(self.msg))
'''

BridgeBase_template = '''
class BridgeBase():
	def __init__(self):
		self._cmd_defers = {}
		self._last_cmd_id = 0

	def _next_cmd_id(self):
		self._last_cmd_id += 1
		return self._last_cmd_id

	def _send_msg(self, msg):
		raise NotImplementedError()

	def _dispatch_msg(self, msg):
		msg_type, name, params = _decode(msg)
		self._validate_received_msg(msg_type, name, params)
		if msg_type == MSG_TYPE_RESPONSE:
			self._on_response(name, params)
			return
		if msg_type == MSG_TYPE_COMMAND:
			receiver_method_name = generate_command_receiver_name(name)
		else:
			raise Exception()
		self.dispatch_msg_hook(msg_type, name, params)
		receiver_method = getattr(self, receiver_method_name)
		receiver_method(*params)

	def _gen_msg(self, msg_type, msg_name, params):
		self.gen_msg_hook(msg_type, msg_name, params)
		return _encode(msg_type, msg_name, params)

	def gen_msg_hook(self, msg_type, msg_name, params):
		pass
	def dispatch_msg_hook(self, msg_type, name, params):
		pass

	def _validate_received_msg(self, msg_type, name, params):
		if msg_type == MSG_TYPE_RESPONSE:
			self._validate_received_responce_valid(name, params)
		elif msg_type == MSG_TYPE_COMMAND:
			self._validate_received_command_valid(name, params)
		else:
			raise InvalidMsgException('invalide msg type', (msg_type, name, params))

	def _validate_received_command_valid(self, name, params):
		for command in self.commands_to_receive:
			command_name = command['name']
			command_params = command['parameters']
			if name != command_name:
				continue
			if len(command_params) != len(params):
				return False
			for i in range(len(params)):
				if not isinstance(params[i], command_params[i]['type']):
					raise InvalidMsgException('invalide command params', (name, params))
			return True
		raise InvalidMsgException('no such command', (name, params))

	def _validate_received_responce_valid(self, name, params):
		if name == '_error':
			if not (len(params) == 2 and isinstance(params[1], str)):
				raise InvalidMsgException('invalide error response : ', (params,))
			return
		for command in self.commands_to_send:
			if 'returns' not in command:
				continue
			command_name = command['name']
			command_returns = command['returns']
			if name != command_name:
				continue
			if len(command_returns) != len(params):
				raise InvalidMsgException('response params count not match', (name, params))
			for i in range(len(params)):
				if not isinstance(params[i], command_returns[i]['type']):
					raise InvalidMsgException('invalide response params', (name, params))
			return
		raise InvalidMsgException('no such command', (name, params))

	def _on_response(self, name, params):
		cmd_id = params[0]
		if not cmd_id in self._cmd_defers:
			raise InvalidMsgException('no such cmd_id : %d'%cmd_id, params)
		d = self._cmd_defers[cmd_id]
		del self._cmd_defers[cmd_id]
		if name == '_error':
			assert len(params) == 2
			d.errback(Exception(params[1]))
		else:
			d.callback(params[1:])

	def responde_error(self, cmd_id, reason):
		msg = self._gen_msg(MSG_TYPE_RESPONSE, '_error', (cmd_id,reason))
		self._send_msg(msg)
'''

BridgeClientBase_template = '''
class BridgeClientBase(BridgeBase):
	commands_to_send = common_commands + client_commands
	commands_to_receive = common_commands + server_commands
'''

BridgeServerBase_template = '''
class BridgeServerBase(BridgeBase):
	commands_to_send = common_commands + server_commands
	commands_to_receive = common_commands + client_commands
'''

test_file_header = '''
#don't modify this file
#this file is generated from bridge_generator.py and bridge_def.py

from twisted.trial import unittest
from connbridge.bridgebase import BridgeClientBase, BridgeServerBase


class TestBridgeMixin(unittest.TestCase):
	def __init__(self):
		self._msgs_to_send = []
		self._expection = []
	def _send_msg(self, msg):
		assert isinstance(msg, str)
		self._msgs_to_send.append(msg)
	def flush_msgs(self):
		for msg in self._msgs_to_send:
			self._remote._dispatch_msg(msg)
		del self._msgs_to_send[:]
	def msg_count(self):
		return len(self._msgs_to_send)
	def has_msg(self):
		return self.msg_count() > 0
	def has_expection(self):
		return bool(self._expection)
	def set_test_case(self, test_case):
		self._test_case = test_case
	def set_remote(self, remote):
		self._remote = remote
	def _gen_msg(self, msg_type, msg_name, params):
		self._remote._expection.append([msg_name, params])
		return self._base._gen_msg(self, msg_type, msg_name, params)
	def _on_response(self, name, params):
		self._test_case.assertTrue(self._expection)
		_, expected_params = self._expection[0]
		del self._expection[0]
		self._test_case.assertEqual(params, expected_params)
		self._base._on_response(self, name, params)
'''

TestBridgeClientBase_template = '''
class TestBridgeClientBase(TestBridgeMixin, BridgeClientBase):
	_base = BridgeClientBase
	def __init__(self):
		BridgeClientBase.__init__(self)
		TestBridgeMixin.__init__(self)

'''

TestBridgeServerBase_template = '''
class TestBridgeServerBase(TestBridgeMixin, BridgeServerBase):
	_base = BridgeServerBase
	def __init__(self):
		BridgeServerBase.__init__(self)
		TestBridgeMixin.__init__(self)
'''

test_expected_msg_template = '''
		self._test_case.assertTrue(self._expection)
		(expected_msg_name, expected_params) = self._expection[0]
		del self._expection[0]
		self._test_case.assertEqual(expected_msg_name, '%s')
		self._test_case.assertEqual(expected_params, %s)
'''.strip('\n\r')

def generate_command_sender_name(name):
	return name

def generate_command_receiver_name(name):
	return 'on_%s'%(name)

def generate_response_sender_name(name):
	return 'responde_%s'%(name)

def _gen_sender(msg_type_str, name_generator, defination):
	msg_name = defination['name']
	method_name = name_generator(msg_name)
	param_names = []
	statements = []
	if msg_type_str == 'MSG_TYPE_RESPONSE':
		params_def = defination.get('returns')
	else:
		params_def = defination.get('parameters')
	deal_with_cmd_id = msg_type_str == 'MSG_TYPE_COMMAND' and params_def and params_def[0]['name'] == 'cmd_id'
	if deal_with_cmd_id:
		statements.append('\t\tcmd_id = self._next_cmd_id()')
	if params_def:
		for param_def in params_def:
			param_name = param_def['name']
			param_type = param_def['type']
			param_names.append(param_name)
			statements.append('\t\tassert isinstance(%s,%s)'%(param_name,param_type.__name__))
	statements.append('\t\tmsg = self._gen_msg(%s, \'%s\', %s)'%(msg_type_str, msg_name, '(%s)'%','.join(param_names+[''])))
	statements.append('\t\tself._send_msg(msg)')
	if deal_with_cmd_id:
		statements.append('\t\td = defer.Deferred()')
		statements.append('\t\tself._cmd_defers[cmd_id] = d')
		statements.append('\t\treturn d')
	method_param_names = param_names if not deal_with_cmd_id else param_names[1:]
	return method_template%(method_name, ', '.join(['self']+method_param_names), '\n'.join(statements))

def _gen_receiver(name_generator, defination, is_test=False):
	msg_name = defination['name']
	method_name = name_generator(msg_name)
	param_names = []
	statements = []
	for param_def in defination['parameters']:
		param_name = param_def['name']
		param_names.append(param_name)
	if not is_test:
		statements.append('\t\traise NotImplementedError()')
	else:
		param_list_str = '(%s)'%(','.join(param_names),)
		statements.append(test_expected_msg_template % (msg_name, param_list_str))
	return method_template%(method_name, ', '.join(['self'] + param_names), '\n'.join(statements))

_dir_name = os.path.dirname(__file__)
file_to_gen = os.path.join(_dir_name, '_bridgebase.py')
_depends = [os.path.join(_dir_name,'bridge_generator.py'), os.path.join(_dir_name,'bridge_def.py')]

test_file_to_gen = os.path.join(_dir_name, 'test', '_test_bridgebase.py')

objects_to_add = [
	generate_command_receiver_name,
]

def gen_protocol_if_needed():
	mtime = os.stat(file_to_gen).st_mtime if os.path.exists(file_to_gen) else -1
	for depend in _depends:
		if os.stat(depend).st_mtime > mtime:
			gen_protocol()
			break

def gen_protocol():
	with open(file_to_gen, 'wb') as f:
		f.write(_file_header)
		for obj in objects_to_add:
			f.write(''.join(inspect.getsourcelines(obj)[0]))
		gen_common(f)
		gen_client(f)
		gen_server(f)

def _gen(f, header, commands_to_send, commands_to_receive):
	str_arr = []
	str_arr.append(header)
	for command in commands_to_send:
		str_arr.append(_gen_sender("MSG_TYPE_COMMAND", generate_command_sender_name, command))
	for command in commands_to_receive:
		str_arr.append(_gen_receiver(generate_command_receiver_name, command))
		if 'returns' in command:
			str_arr.append(_gen_sender('MSG_TYPE_RESPONSE', generate_response_sender_name, command))
	for s in str_arr:
		f.write(s)

def gen_common(f):
	_gen(f, BridgeBase_template, common_commands, common_commands)

def gen_client(f):
	_gen(f, BridgeClientBase_template, client_commands, server_commands)

def gen_server(f):
	_gen(f, BridgeServerBase_template, server_commands, client_commands)

def gen_test_protocol_if_needed():
	test_mtime = os.stat(test_file_to_gen).st_mtime if os.path.exists(test_file_to_gen) else -1
	for depend in _depends:
		if os.stat(depend).st_mtime > test_mtime:
			gen_test_protocol()
			break

def gen_test_protocol():
	with open(test_file_to_gen, 'wb') as f:
		f.write(test_file_header)
		gen_test_client(f)
		gen_test_server(f)

def gen_test_client(f):
	str_arr = []
	str_arr.append(TestBridgeClientBase_template)
	for command in (common_commands + server_commands):
		str_arr.append(_gen_receiver(generate_command_receiver_name, command, is_test=True))
	for s in str_arr:
		f.write(s)

def gen_test_server(f):
	str_arr = []
	str_arr.append(TestBridgeServerBase_template)
	for command in (common_commands + client_commands):
		str_arr.append(_gen_receiver(generate_command_receiver_name, command, is_test=True))
	for s in str_arr:
		f.write(s)
