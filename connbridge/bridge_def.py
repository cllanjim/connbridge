common_commands = [
	{
		'name' : 'cb_send',
		'parameters' : [
			{ 'name' : 'id', 'type' : int },
			{ 'name' : 'data', 'type' : str, 'verylong' : True},
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

client_commands = [
	{
		'name' : 'login',
		'parameters' : [
			{ 'name' : 'version', 'type' : str },
			{ 'name' : 'user_name', 'type' : str },
			{ 'name' : 'password', 'type' : str}
		],
		'returns' : [
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
		],
	},

]

server_commands = [
]

for commands in (common_commands, client_commands, server_commands):
	for cmd in commands:
		if 'returns' in cmd:
			cmd['parameters'].insert(0, {'name' : 'cmd_id', 'type' : int})
			cmd['returns'].insert(0, {'name' : 'cmd_id', 'type' : int})
