from twisted.trial import unittest
from twisted.test.proto_helpers import StringTransport
from twisted.internet.protocol import Protocol
from connbridge.bridgebase import BridgeBase
from connbridge import bridge_generator

bridge_generator.gen_test_protocol_if_needed()
execfile(bridge_generator.test_file_to_gen)

class BridgeBaseTest(unittest.TestCase):
	def _build(self):
		client = TestBridgeClientBase()
		server = TestBridgeServerBase()
		client.set_remote(server)
		server.set_remote(client)
		client.set_test_case(self)
		server.set_test_case(self)
		return (client, server)
	def _loop(self, client, server):
		while client.has_msg() or server.has_msg():
			client.flush_msgs()
			server.flush_msgs()
		self.assertFalse(client.has_expection())
		self.assertFalse(server.has_expection())
	def test_login(self):
		client,server = self._build()
		d = client.login('0.1', 'abc', '123456')
		server.responde_login(client._last_cmd_id)
		self.assertEqual(client.msg_count(), 1)
		self.assertEqual(server.msg_count(), 1)
		self._loop(client, server)
		return d
	def test_client_cb_send(self):
		client,server = self._build()
		client.cb_send(2, 'hello,world')
		self._loop(client, server)
	def test_server_cb_send(self):
		client,server = self._build()
		server.cb_send(2, 'hello,world')
		self._loop(client, server)
