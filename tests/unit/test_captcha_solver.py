import unittest
from unittest.mock import MagicMock, patch
from titlepro.search.captcha_solver import CaptchaSolver

class DummyDriver:
    def __init__(self):
        self.scripts = []
        self.attrs = {}
    def execute_script(self, script, *args, **kwargs):
        self.scripts.append((script, args))
        return 'dGVzdGltYWdlYmFzZTY0'  # Dummy base64
    def find_element(self, by, value):
        class E:
            def get_attribute(_self, attr):
                if attr == 'src':
                    return 'data:image/png;base64,dGVzdGltYWdlYmFzZTY0'
                if attr == 'data-sitekey':
                    return 'dummy_sitekey'
                return None
            def clear(_self):
                pass
            def send_keys(_self, val):
                pass
        return E()

class TestCaptchaSolver(unittest.TestCase):
    @patch('requests.Session.post')
    @patch('requests.Session.get')
    def test_solve_recaptcha_v2_success(self, mock_get, mock_post):
        mock_post.return_value.json.return_value = {'status': 1, 'request': 'capid'}
        mock_get.return_value.json.side_effect = [
            {'status': 0, 'request': 'CAPCHA_NOT_READY'},
            {'status': 1, 'request': 'tokenabc'}
        ]
        d = DummyDriver()
        solver = CaptchaSolver(d, twocaptcha_api_key='dummy')
        token = solver.solve_recaptcha_v2('dummy_sitekey', 'http://example.com')
        self.assertEqual(token, 'tokenabc')

    @patch('requests.Session.post')
    @patch('requests.Session.get')
    def test_solve_image_captcha_success(self, mock_get, mock_post):
        mock_post.return_value.json.return_value = {'status': 1, 'request': 'imgcapid'}
        mock_get.return_value.json.side_effect = [
            {'status': 0},
            {'status': 1, 'request': 'imgsolution'}
        ]
        d = DummyDriver()
        solver = CaptchaSolver(d, twocaptcha_api_key='dummy')
        img_element = d.find_element(None, None)
        sol = solver.solve_image_captcha(img_element)
        self.assertEqual(sol, 'imgsolution')

    def test_fallback_manual(self):
        d = DummyDriver()
        solver = CaptchaSolver(d, twocaptcha_api_key=None)
        with patch('builtins.input', return_value='abcdxyz'):
            val = solver.fallback_manual_captcha()
        self.assertEqual(val, 'abcdxyz')

    def test_auto_bypass_errors(self):
        # API key missing
        d = DummyDriver()
        solver = CaptchaSolver(d)
        self.assertIsNone(solver.solve_recaptcha_v2('dummy', 'http://x'))
        self.assertIsNone(solver.solve_image_captcha(d.find_element(None, None)))

if __name__ == '__main__':
    unittest.main()
