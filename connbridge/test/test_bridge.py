from twisted.trial import unittest
from twisted.test.proto_helpers import StringTransport
from twisted.internet.protocol import Protocol
from twisted.internet.defer import DeferredList
from connbridge.bridge import DefaultBridgeClient, DefaultBridgeServer
from connbridge.bridge import LoginException, UnloginException
from connbridge.cbconnection import CBConnection

class _DummyPassUserManager:
	def login(self, username, password):
		return True

class _DummyFailUserManager:
	def login(self, username, password):
		return False

class TestServerConnection(CBConnection):
	def __init__(self, bridge, id, host, port, cb_connect_cmd_id):
		CBConnection.__init__(self, bridge, id)
		self.bridge.responde_cb_connect(cb_connect_cmd_id)
		self.data = ''
	def on_remote_data_received(self, data):
		self.data += data
	def clear(self):
		self.data = ''
	def take_data(self):
		data = self.data
		self.data = ''
		return data

class TestCBConnectionClient:
	def __init__(self):
		self.connected = False
		self.connect_failed = False
		self.connection_lost = False
		self.data = ''
	def cb_connected(self):
		self.connected = True
	def cb_connect_failed(self):
		self.connect_failed = True
	def cb_data_received(self, data):
		print 'cb_data_received'
		self.data += data
	def cb_connection_lost(self):
		self.connection_lost = True
	def clear():
		self.data = ''
	def take_data(self):
		data = self.data
		self.data = ''
		return data

class TestBridgeClient(DefaultBridgeClient):
	pass

class TestBridgeServer(DefaultBridgeServer):
	connection_factory = TestServerConnection

class _TestCaseMixin:
	def setUp(self):
		self.client = TestBridgeClient()
		self.client.raise_exception = True
		self.client_tr = StringTransport()
		self.client.makeConnection(self.client_tr)
		self.server = TestBridgeServer(None)
		self.server.raise_exception = True
		self.server_tr = StringTransport()
		self.server.makeConnection(self.server_tr)

	def _feed_server(self):
		data = self.client_tr.value()
		self.client_tr.clear()
		self.assertTrue(data)
		self.server.dataReceived(data)

	def _feed_client(self):
		data = self.server_tr.value()
		self.server_tr.clear()
		self.assertTrue(data)
		self.client.dataReceived(data)

	def _assertClientRaise(self, e):
		with self.assertRaises(e):
			self._feed_client()

	def _assertServerRaise(self, e):
		with self.assertRaises(e):
			self._feed_server()

login_data = ('0.1', 'abc', '123456')
remote_addr = ('127.0.0.1', 8080)

class BridgeLoginTest(_TestCaseMixin, unittest.TestCase):
	def test_login_pass(self):
		self.server.user_manager = _DummyPassUserManager()
		d = self.client.login(*login_data)
		self._feed_server()
		self._feed_client()
		self.assertTrue(self.client._logined)
		return d

	def test_login_fail(self):
		self.server.user_manager = _DummyFailUserManager()
		d = self.client.login(*login_data)
		self._assertServerRaise(LoginException)
		self._feed_client()
		self.assertFalse(self.client._logined)
		return d

	def test_send_msg_before_login(self):
		self.server.user_manager = _DummyPassUserManager()
		self.client.cb_connect(*remote_addr, client=None)
		self._assertServerRaise(UnloginException)

	def test_send_msg_before_login_succeed(self):
		self.server.user_manager = _DummyPassUserManager()
		self.client.login(*login_data)
		cb_client = TestCBConnectionClient()
		self.client.cb_connect(*remote_addr, client=cb_client)
		self._feed_server()
		self.assertTrue(len(self.server._connections) == 1)

class BridgeTest(_TestCaseMixin, unittest.TestCase):
	def setUp(self):
		_TestCaseMixin.setUp(self)
		self.server.user_manager = _DummyPassUserManager()
		d = self.client.login(*login_data)

	def _connect(self):
		self.cb_client = TestCBConnectionClient()
		self.client_connection = self.client.cb_connect(*remote_addr, client=self.cb_client)
		self._feed_server()
		self.assertTrue(len(self.server._connections) == 1)
		self.server_connection = self.server._connections[1]

	def test_cb_connect(self):
		self._connect()
		self._feed_client()
		self.assertTrue(self.cb_client.connected)

	def test_client_cb_send(self):
		self.test_cb_connect()
		self.client_connection.send('hello')
		self._feed_server()
		self.assertEqual(self.server_connection.take_data(), 'hello')
		self.server_connection.send('responde hello')
		self._feed_client()
		self.assertEqual(self.cb_client.take_data(), 'responde hello')