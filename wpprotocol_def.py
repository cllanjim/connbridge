commands = [
	{
		'name' : 'login',
		'parameters' : [
			{ 'name' : 'version', 'type' : str },
			{ 'name' : 'user_name', 'type' : str },
			{ 'name' : 'password', 'type' : str}
		],
		'returns' : [
			{ 'name' : 'ok', 'type' : bool },
			{ 'name' : 'err_reason', 'type' : str}
		]
	},
	{
		'name' : 'connect',
		'parameters' : [
			{ 'name' : 'id', 'type' : int },
			{ 'name' : 'host', 'type' : str },
			{ 'name' : 'port', 'type' : int}
		],
		'returns' : [
			{ 'name' : 'ok', 'type' : bool },
			{ 'name' : 'err_reason', 'type' : str}
		],
	},
	{
		'name' : 'connection_send',
		'parameters' : [
			{ 'name' : 'id', 'type' : int },
			{ 'name' : 'data', 'type' : str},
		],
		'returns' : [
			{ 'name' : 'ok', 'type' : bool },
			{ 'name' : 'err_reason', 'type' : str },
		]
	},
	{
		'name' : 'close_connection',
		'parameters' : [
			{ 'name' : 'id', 'type' : int}
		]
	},
	{
		'name' : 'close_link',
		'parameters' : [
			{ 'name' : 'reason', 'type' : str}
		]
	}
]

events = [
	{
		'name' : 'connection_data_received',
		'parameters' : [
			{ 'name' : 'id', 'type' : int },
			{ 'name' : 'data', 'type' : str},
		]
	},
	{
		'name' : 'connection_lost',
		'parameters' : [
			{ 'name' : 'id', 'type' : int },
			{ 'name' : 'reason', 'type' : str},
		]
	}
]

client_protocol_encoder = None
client_protocol_decoder = None
server_procotol_encoder = None
server_procotol_decoder = None
ClientProtocolMixin = None
ServerProtocolMixin = None