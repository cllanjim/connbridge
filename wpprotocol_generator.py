from string import Template
import os
from wpprotocol_def import commands,events

FIRST_MSG_TYPE = 1
LAST_MSG_TYPE = 3
(MSG_TYPE_COMMAND,
	MSG_TYPE_RESPONCE,
	MSG_TYPE_EVENT
) = range(FIRST_MSG_TYPE,LAST_MSG_TYPE+1)

def _encode(msg_type, name, params):
	assert isinstance(params, list) or isinstance(params, tuple)
	assert msg_type >= FIRST_MSG_TYPE and msg_type <= LAST_MSG_TYPE
	assert len(params) < 256
	data_arr = [struct.pack('!BB%dsB'%(len(name)), msg_type, len(name), name, len(params))]
	for param in params:
		if isinstance(param, str):
			p = struct.pack('!BI%ds'%(len(param)), 's', len(param), param)
		elif isinstance(param, int):
			p = struct.pack('!Bi', 'i', param)
		elif isinstance(param, bool):
			p = struct.pack('!B?', 'b', param)
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
	cur = 0
	def next(n=1):
		ret = data[cur:cur+n]
		cur += n
		return ret
	(msg_type, name_len) = struct.unpack('!BB', next(2))
	name = next(name_len)
	params_count = _unpack('!B', next())
	params = []
	for i in range(params_count):
		param_type = _unpack('!B', next())
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
	return (msg_type, name, params)

method_template = '''
	def %s(%s):
%s
'''

wpprotocolbase_header = '''
#don't modify this file
#this file is generated from wpprotocol_generator.py and wpprotocol_def.py

class WPProtocolBase():
	def _send_msg(self, msg):
		raise NotImplementedError()

	def _dispatch_msg(self, msg_type, name, params):
		if not self._is_received_msg_valid(msg_type, name, params):
			raise Exception()
		if msg_type == MSG_TYPE_RESPONCE:
			pass
			return
		if msg_type == MSG_TYPE_COMMAND:
			receiver_method_name = generate_command_receiver_name(name)
		elif msg_type == MSG_TYPE_EVENT:
			receiver_method_name = generate_event_receiver_name(name)
		else:
			raise Exception()
		receiver_method = getattr(self, receiver_method_name)
		receiver_method(params)
'''

WPClientProtocolBase_template = '''
class WPClientProtocolBase():
	def _is_received_msg_valid(self, msg_type, name, params):
		if msg_type == MSG_TYPE_RESPONCE:
			return self._is_received_responce_valid(name, params)
		elif msg_type == MSG_TYPE_EVENT:
			return self._is_received_event_valid(name, params)
		else:
			return False

	def _is_received_responce_valid(self, params)
		for command in commands:
			command_name = command['name']
			command_returns = command['returns']
			if name != command_name:
				continue
			if len(command_returns) != len(params):
				return False
			for i in range(len(params)):
				if not isinstance(params[i], command_returns[i].type):
					return False
			return True
		return False
'''

WPServerProtocolBase_template = '''
class WPServerProtocolBase():
	def _is_received_msg_valid(self, msg_type, name, params):
		if msg_type == MSG_TYPE_COMMAND:
			return self._is_received_command_valid(name, params)
		else:
			return False

	def _is_received_command_valid(self, params)
		for command in commands:
			command_name = command['name']
			command_params = command['parameters']
			if name != command_name:
				continue
			if len(command_params) != len(params):
				return False
			for i in range(len(params)):
				if not isinstance(params[i], command_params[i].type):
					return False
			return True
		return False
'''

def generate_command_sender_name(name):
	return name

def generate_command_receiver_name(name):
	return 'on_%s'%(name)

def generate_response_sender_name(name):
	return 'responed_%s'%(name)

def generate_event_sender_name(name):
	return 'fire_%s'%(name)

def generate_event_receiver_name(name):
	return 'on_%s'%(name)

def _gen_sender(msg_type_str, name_generator, defination):
	msg_name = defination['name']
	method_name = name_generator(msg_name)
	param_names = []
	statements = []
	if msg_type_str == 'MSG_TYPE_RESPONCE':
		params_def = defination.get('parameters')
	else:
		params_def = defination.get('returns')
	if params_def:
		for param_def in params_def:
			param_name = param_def['name']
			param_type = param_def['type']
			param_names.append(param_name)
			statements.append('\t\tassert isinstance(%s,%s)'%(param_name,param_type))
	statements.append('\t\tmsg = _encode(%s, %s, %s)'%(msg_type_str, msg_name, '(%s,)'%','.join(param_names)))
	statements.append('\t\tself._send_msg(msg)')
	return method_template%(method_name, ', '.join(['self']+param_names), '\n'.join(statements))

def _gen_receiver(name_generator, defination):
	msg_name = defination['name']
	method_name = name_generator(msg_name)
	param_names = []
	statements = []
	for param_def in defination['parameters']:
		param_name = param_def['name']
		param_names.append(param_name)
	statements.append('\t\traise NotImplementedError()')
	return method_template%(method_name, ', '.join(['self'] + param_names), '\n'.join(statements))

_dir_name = os.path.dirname(__file__)
_file_to_generator = os.path.join(_dir_name, 'wpprotocolbase.py')
_depends = [os.path.join(_dir_name,'wpprotocol_generator.py'), os.path.join(_dir_name,'wpprotocol_def.py')]

def gen_protocol_if_needed():
	mtime = os.stat(_file_to_generator).st_mtime
	for depend in _depends:
		if os.stat(depend).st_mtime > mtime:
			gen_protocol()
			break

def gen_protocol():
	with open(_file_to_generator, 'wb') as f:
		f.write(wpprotocolbase_header)
		gen_client_protocol(f)
		gen_server_protocol(f)

def gen_client_protocol(f):
	str_arr = []
	str_arr.append(WPClientProtocolBase_template)
	for command in commands:
		str_arr.append(_gen_sender("MSG_TYPE_COMMAND", generate_command_sender_name, command))
	for event in events:
		str_arr.append(_gen_receiver(generate_event_receiver_name, event))
	for s in str_arr:
		f.write(s)

def gen_server_protocol(f):
	str_arr = []
	str_arr.append(WPServerProtocolBase_template)
	for command in commands:
		str_arr.append(_gen_receiver(generate_command_receiver_name, command))
	for event in events:
		str_arr.append(_gen_sender('MSG_TYPE_EVENT', generate_event_sender_name, event))
	for command in commands:
		if 'returns' in command:
			str_arr.append(_gen_sender('MSG_TYPE_EVENT', generate_response_sender_name, command))
	for s in str_arr:
		f.write(s)