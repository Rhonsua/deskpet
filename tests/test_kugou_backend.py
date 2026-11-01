import unittest
from deskpet.music.kugou.service import Service, ApiError
from deskpet.music.kugou.media import validate_media_url
from deskpet.music.kugou.links import playlist_id

class KugouBackendTests(unittest.TestCase):
    def test_account_response_info_without_total(self):
        # Sanitized shape observed from the ordinary Kugou account endpoint.
        g=Service({'userid':'42','token':'secret'}).collections(); next(g)
        with self.assertRaises(StopIteration) as result:
            g.send({'status':1,'error_code':0,'data':{
                'info':[{'listid':101,'type':0,'name':'歌单一','count':0},
                        {'listid':102,'type':0,'name':'歌单二','count':2},
                        {'listid':103,'type':1,'name':'收藏','count':1}],
                'list_count':3,'collect_count':0,'album_count':0,'total_ver':6}})
        self.assertEqual([x['id'] for x in result.exception.value['playlists']],
                         ['user_101_0','user_102_0','user_103_1'])
        self.assertTrue(result.exception.value['complete'])

    def test_account_info_pagination_uses_raw_rows_not_category_counts(self):
        import json
        g=Service({'userid':'42','token':'secret'}).collections(); next(g)
        batch=[{'listid':i,'type':0,'name':'歌单'} for i in range(30)]
        request=g.send({'data':{'info':batch,'list_count':1,'collect_count':1}})
        self.assertEqual(json.loads(request.body)['page'],2)
        with self.assertRaises(StopIteration) as result:
            g.send({'data':{'info':[{'listid':30,'type':1,'name':'收藏'}]}})
        self.assertEqual(len(result.exception.value['playlists']),31)
        self.assertTrue(result.exception.value['complete'])

    def test_account_repeated_page_and_later_failure_keep_partial_results(self):
        batch=[{'listid':i,'type':0,'name':'歌单'} for i in range(30)]
        for repeat in (True,False):
            g=Service({'userid':'42','token':'secret'}).collections(); next(g)
            g.send({'data':{'info':batch}})
            with self.assertRaises(StopIteration) as result:
                if repeat: g.send({'data':{'info':batch}})
                else: g.throw(ApiError('测试连接中断'))
            self.assertEqual(len(result.exception.value['playlists']),30)
            self.assertFalse(result.exception.value['complete'])
            self.assertTrue(result.exception.value['warnings'])

    def test_account_empty_and_malformed_are_distinct(self):
        g=Service({'userid':'42','token':'secret'}).collections(); next(g)
        with self.assertRaises(StopIteration) as result: g.send({'data':{'info':[],'list_count':0}})
        self.assertEqual(result.exception.value['playlists'],[])
        self.assertTrue(result.exception.value['complete'])
        for data in ({'list_count':3}, {'info':None}, {'info':[],'total':'invalid'}):
            g=Service({'userid':'42','token':'secret'}).collections(); next(g)
            with self.assertRaises(ApiError): g.send({'data':data})

    def test_search_normalizes_and_marks_partial(self):
        g=Service().search('test'); next(g)
        with self.assertRaises(StopIteration) as result:
            g.send({'data':{'total':2,'lists':[{'hash':'a'*32,'songname':'Test','duration':10}]}})
        value=result.exception.value
        self.assertEqual(value['tracks'][0]['id'],'A'*32)
        self.assertEqual(value['tracks'][0]['duration'],10000)
        self.assertFalse(value['complete'])
    def test_qr_status(self):
        g=Service().qr_check('abc'); next(g)
        with self.assertRaises(StopIteration) as result: g.send({'data':{'status':2}})
        self.assertEqual(result.exception.value['status'],'scanned')
    def test_private_playlist_routes_and_scopes_session(self):
        import json
        session={'userid':'42','token':'secret'}
        service=Service(session)
        g=service.collections(); req=next(g)
        self.assertEqual(req.headers['x-router'],'cloudlist.service.kugou.com')
        with self.assertRaises(StopIteration) as result:
            g.send({'data':{'total':1,'list':[{'listid':123,'type':1,'name':'Favorites'}]}})
        self.assertEqual(result.exception.value['playlists'][0]['id'],'user_123_1')
        g=service.playlist('user_123_1'); req=next(g)
        self.assertEqual(req.url,'https://gateway.kugou.com/v4/get_list_all_file_v3')
        self.assertEqual(req.headers['x-router'],'cloudlist.service.kugou.com')
        self.assertEqual(json.loads(req.body)['token'],'secret')
        with self.assertRaises(StopIteration) as result:
            g.send({'data':{'count':1,'songs':[{'hash':'a'*32,'name':'Song','timelen':1200}]}})
        self.assertTrue(result.exception.value['complete'])
        for operation in (service.search('x'),service.song('A'*32),service.qr_create(),service.playlist('collection_3_1_2_0')):
            request=next(operation)
            self.assertNotIn('secret',str(request.params)+request.body)
    def test_missing_total_fails_and_invalid_track_is_partial(self):
        g=Service().collections()
        with self.assertRaises(ApiError): next(g)
        g=Service().playlist('collection_3_1_2_0'); next(g)
        with self.assertRaises(ApiError): g.send({'data':{'songs':[]}})
        g=Service().playlist('collection_3_1_2_0'); next(g)
        with self.assertRaises(StopIteration) as result: g.send({'data':{'count':2,'songs':[{'hash':'a'*32},{'hash':'bad'}]}})
        self.assertFalse(result.exception.value['complete'])
        self.assertEqual(result.exception.value['missing_pages'],[1])
        self.assertTrue(result.exception.value['warnings'])
    def test_resolve_official_redirect_and_reject_external(self):
        g=Service().resolve_playlist('分享 https://v.kugou.com/abc 点开')
        req=next(g); self.assertTrue(req.redirect_probe)
        req=g.send({'location':'https://www.kugou.com/?global_specialid=collection_3_1_2_0'})
        self.assertIn('get_other_list_file_nofilt',req.url)
        g=Service().resolve_playlist('https://v.kugou.com/abc'); next(g)
        with self.assertRaises(ValueError): g.send({'location':'https://example.com/?global_specialid=collection_3_1_2_0'})
    def test_urls(self):
        self.assertEqual(playlist_id('https://www.kugou.com/?global_specialid=collection_3_1_2_0'),'collection_3_1_2_0')
        with self.assertRaises(ValueError): playlist_id('https://www.kugou.com/?specialid=123')
        with self.assertRaises(ValueError): validate_media_url('https://webfs.kugou.com.evil.test/a.mp3')
        with self.assertRaises(ValueError): validate_media_url('https://webfs.kugou.com/a/../b.mp3')

if __name__=='__main__': unittest.main()
