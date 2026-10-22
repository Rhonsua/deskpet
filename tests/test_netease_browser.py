from http.cookies import SimpleCookie
import unittest

from netease_player_worker import official_page, login_cookie


class BrowserBoundaryTests(unittest.TestCase):
    def test_only_official_https_top_level(self):
        self.assertTrue(official_page('https://music.163.com/#/my/'))
        for url in ('http://music.163.com/', 'https://music.163.com.evil.test/',
                    'https://evil.test/?music.163.com', 'https://user@music.163.com/',
                    'https://music.163.com:444/', 'file:///tmp/page', 'javascript:alert(1)', None):
            self.assertFalse(official_page(url), url)

    def test_only_known_cookies_from_owned_official_profile(self):
        cookies = []
        for name, value, domain, path in [('MUSIC_U', 'fake', '.music.163.com', '/'),
                                          ('__csrf', 'fake-csrf', '.163.com', '/'),
                                          ('unrelated', 'ignore', '.163.com', '/'),
                                          ('MUSIC_U', 'evil', '.evil.test', '/'),
                                          ('MUSIC_U', 'wrong-path', '.music.163.com', '/other')]:
            jar = SimpleCookie()
            jar[name] = value
            jar[name]['domain'] = domain
            jar[name]['path'] = path
            cookies.append(jar)
        self.assertEqual(login_cookie(cookies), 'MUSIC_U=fake; __csrf=fake-csrf')


if __name__ == '__main__':
    unittest.main()
