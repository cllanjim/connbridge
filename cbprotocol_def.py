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
		'name' : 'cb_connect',
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
		'name' : 'cb_send',
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
		'name' : 'cb_close',
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
		'name' : 'cb_data_received',
		'parameters' : [
			{ 'name' : 'id', 'type' : int },
			{ 'name' : 'data', 'type' : str},
		]
	},
	{
		'name' : 'cb_connection_lost',
		'parameters' : [
			{ 'name' : 'id', 'type' : int },
			{ 'name' : 'reason', 'type' : str},
		]
	}
]

for cmd in commands:
	if 'returns' in cmd:
		cmd['parameters'].insert(0, {'name' : 'cmd_id', 'type' : int})
		cmd['returns'].insert(0, {'name' : 'cmd_id', 'type' : int})
