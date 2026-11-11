import sqlite3
import unittest
from unittest.mock import Mock
import sync_notion as sn


def run(status='FINISHED'):
    return {'info': {'run_id': 'abc', 'experiment_id': '1', 'start_time': 1000, 'status': status},
            'data': {'tags': [{'key': 'source', 'value': 'service'}],
                     'metrics': [{'key': 'python_pipeline_sec', 'value': 8.2}]}}


class FakeMLflow:
    uri = 'http://localhost:5000'
    def __init__(self):
        self.rows = [run('RUNNING'), run()]
    def call(self, path, body):
        if path == 'experiments/search':
            return {'experiments': [{'experiment_id': '1', 'name': 'demo'}]}
        return {'runs': self.rows}


class NotionTests(unittest.TestCase):
    def setUp(self):
        self.state = sqlite3.connect(':memory:')
        self.state.execute('CREATE TABLE synced(key TEXT PRIMARY KEY, digest TEXT)')
    def tearDown(self):
        self.state.close()
    def test_timing_and_missing_dice(self):
        p = sn.properties(run(), 'demo', 'http://localhost:5000')
        self.assertEqual(p['Pipeline_s']['number'], 8.2)
        self.assertIsNone(p['Inference_s']['number'])
        self.assertIsNone(p['Dice']['number'])
        self.assertEqual(p['Started']['date']['start'], '1970-01-01T00:00:01+00:00')
    def test_terminal_only_and_unchanged_skip(self):
        api, notion = FakeMLflow(), Mock()
        sn.cycle(api, notion, 'source', self.state, api.uri)
        sn.cycle(api, notion, 'source', self.state, api.uri)
        self.assertEqual(notion.upsert.call_count, 1)
        api.rows[1]['data']['metrics'].append({'key': 'dice_mean', 'value': .8})
        sn.cycle(api, notion, 'source', self.state, api.uri)
        self.assertEqual(notion.upsert.call_count, 2)
    def test_failed_write_not_cached(self):
        api, notion = FakeMLflow(), Mock()
        notion.upsert.side_effect = RuntimeError('offline')
        with self.assertRaises(RuntimeError):
            sn.cycle(api, notion, 'source', self.state, api.uri)
        self.assertEqual(self.state.execute('SELECT count(*) FROM synced').fetchone()[0], 0)
        notion.upsert.side_effect = None
        sn.cycle(api, notion, 'source', self.state, api.uri)
        self.assertEqual(notion.upsert.call_count, 2)
    def test_upsert_existing_page(self):
        notion = sn.Notion('fake')
        notion.call = Mock(side_effect=[{'results': [{'id': 'page'}]}, {}])
        notion.upsert('source', 'abc', {})
        self.assertEqual(notion.call.call_args.args[0:2], ('PATCH', 'pages/page'))
    def test_duplicate_refused(self):
        notion = sn.Notion('fake')
        notion.call = Mock(return_value={'results': [{'id': 'a'}, {'id': 'b'}]})
        with self.assertRaises(ValueError): notion.upsert('source', 'abc', {})
    def test_pagination(self):
        api = Mock()
        api.call.side_effect = [{'runs': [1], 'next_page_token': 'next'}, {'runs': [2]}]
        self.assertEqual(list(sn.paged(api, 'runs/search', {}, 'runs')), [1, 2])
        self.assertEqual(api.call.call_args.args[1]['page_token'], 'next')
    def test_url_is_not_id(self):
        with self.assertRaises(ValueError): sn.notion_id('https://notion.so/example?v=abc')
    def test_create_parent(self):
        notion = sn.Notion('fake')
        notion.call = Mock(side_effect=[{'results': []}, {}])
        notion.upsert('source', 'abc', {})
        self.assertEqual(notion.call.call_args.args[2]['parent'], {'type':'data_source_id','data_source_id':'source'})

if __name__ == '__main__': unittest.main()
