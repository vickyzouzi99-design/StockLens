import copy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from collect_data import (SHANGHAI, ApiError, FuyaoClient, atomic_json, clean_bars,
                          collect_snapshot, publish_snapshot, refresh_lock,
                          report_candidates, run_refresh, to_number, validate_snapshot)
from refresh_worker import due_slot, read_json, should_attempt, tick
from app import CompareRequest, ScreenParams, ScreenRequest, compare, screen, snapshot_path
from fastapi import HTTPException


def stamp(day):
    return int(datetime.combine(day, datetime.min.time(), SHANGHAI).timestamp() * 1000)


class FixtureClient:
    def __init__(self, missing_financial=False):
        self.calls = []
        self.missing_financial = missing_financial
        self.days = [date(2026, 10, 1) + timedelta(days=i) for i in range(47)
                     if (date(2026, 10, 1) + timedelta(days=i)).weekday() < 5]

    def get(self, path, params):
        self.calls.append((path, params))
        if 'trading-days' in path:
            data = {'item': [{'date': day.strftime('%Y%m%d')} for day in self.days]}
        elif 'ths-stock-list' in path:
            data = {'item': [{'thscode': f'{i:06d}.SZ', 'name': f'S{i}'} for i in range(1, 301)]}
        elif 'valuations' in path:
            data = {'item': [{'thscode': code, 'pe_ttm': -2 if code == '000001.SZ' else '20', 'pb_mrq': 2} for code in params['thscodes'].split(',')]}
        elif 'ths-index-list-by-stock' in path:
            data = {'item': [{'thscode': code, 'index_list': [{'thscode': '881155.TI', 'name': '银行', 'type': 'industry'}]} for code in params['thscode'].split(',')]}
        elif 'historical-batch' in path:
            data = {'item': [{'thscode': code, 'item': [{'date_ms': stamp(day), 'close_price': 100+i} for i, day in enumerate(self.days)]} for code in params['thscodes'].split(',')]}
        else:
            # The most recently completed period may not yet have been disclosed.
            indicators = [] if self.missing_financial and params['report'] == '2026-3' else [
                {'index_id': 'calculate_parent_holder_net_profit_yoy_growth_ratio', 'value': '12.5'},
                {'index_id': 'index_weighted_avg_roe', 'value': '8'},
                {'index_id': 'calculate_operating_income_yoy_growth_ratio', 'value': '10'}]
            data = {'thscode': params['thscode'], 'report': params['report'], 'abilities': [{'indicators': indicators}]}
        return {'code': 0, 'request_id': 'fixture', 'data': data}


class CleaningTests(unittest.TestCase):
    def test_finite_values_and_missing(self):
        for raw in [None, '', '--', True, 'NaN', float('inf')]:
            self.assertIsNone(to_number(raw))
        self.assertEqual(to_number('-52.6'), -52.6)
        self.assertEqual(to_number('24.47%'), 24.47)
        self.assertEqual(to_number('0'), 0)

    def test_intraday_and_conflicting_bars(self):
        now = datetime(2026, 11, 16, 13, tzinfo=SHANGHAI)
        bars = [{'date_ms': stamp(date(2026, 11, 13)), 'close_price': 10},
                {'date_ms': stamp(date(2026, 11, 13)), 'close_price': 11},
                {'date_ms': stamp(date(2026, 11, 16)), 'close_price': 12},
                {'date_ms': stamp(date(2026, 11, 12)), 'close_price': 9},
                {'date_ms': stamp(date(2026, 11, 12)), 'close_price': 9},
                {'date_ms': 'bad', 'close_price': 'NaN'}]
        cleaned, removed = clean_bars(bars, now)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]['close_price'], 9)
        self.assertEqual(removed, 3)

    def test_completed_quarters_cross_year(self):
        self.assertEqual(report_candidates(datetime(2027, 1, 1))[:2], ['2026-4', '2026-3'])
        self.assertEqual(report_candidates(datetime(2026, 11, 16))[0], '2026-3')

    def test_300_collection_batching_and_report_fallback(self):
        client = FixtureClient(missing_financial=True)
        data = collect_snapshot(client, now=datetime(2026, 11, 16, 16, tzinfo=SHANGHAI), progress=lambda _: None)
        self.assertEqual(len(data['stocks']), 300)
        self.assertEqual(data['stocks'][0]['pe_ttm'], -2)
        self.assertTrue(all(row['financial_report'] == '2026-2' for row in data['stocks']))
        self.assertTrue(all(row['volatility_20d_pct'] is not None for row in data['stocks']))
        self.assertEqual(len([p for p, _ in client.calls if 'valuations' in p]), 3)
        self.assertEqual(len([p for p, _ in client.calls if 'historical-batch' in p]), 30)
        self.assertEqual(validate_snapshot(data, 300)['pe_ttm'], 1)

    def test_partial_and_total_failure_publication(self):
        data = collect_snapshot(FixtureClient(), limit=5, now=datetime(2026, 11, 16, 16, tzinfo=SHANGHAI), progress=lambda _: None)
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            publish_snapshot(data, directory, 5)
            before = (directory / 'stock_snapshot_latest.json').read_bytes()
            broken = copy.deepcopy(data)
            for row in broken['stocks']:
                row['pe_ttm'] = None
            with self.assertRaises(ValueError):
                publish_snapshot(broken, directory, 5)
            self.assertEqual((directory / 'stock_snapshot_latest.json').read_bytes(), before)
            data['stocks'][0]['pe_ttm'] = None
            self.assertEqual(validate_snapshot(data, 5)['pe_ttm'], 0.8)

    def test_atomic_write_failure_leaves_old_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'snapshot.json'
            atomic_json(path, {'old': True})
            with patch('collect_data.os.replace', side_effect=OSError), self.assertRaises(OSError):
                atomic_json(path, {'new': True})
            self.assertEqual(json.loads(path.read_text()), {'old': True})
            self.assertEqual(list(Path(folder).glob('.pending-*')), [])

    def test_one_writer_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            with refresh_lock(Path(folder)):
                with self.assertRaises(RuntimeError):
                    with refresh_lock(Path(folder)):
                        pass

    def test_http_429_and_business_rate_limit_retry(self):
        client = FuyaoClient('test-only')
        client.session = Mock()
        client.session.get.side_effect = [Mock(status_code=429),
            Mock(status_code=200, ok=True, content=b'{"code":4001}'),
            Mock(status_code=200, ok=True, content=b'{"code":0,"data":{"item":[]}}')]
        with patch('collect_data.time.sleep'):
            self.assertEqual(client.get('/test', {})['code'], 0)
        self.assertEqual(client.session.get.call_count, 3)


class SchedulerTests(unittest.TestCase):
    def test_four_slots_in_shanghai_not_host_timezone(self):
        for h, m in [(9, 30), (11, 30), (13, 0), (15, 0)]:
            now = datetime(2026, 11, 16, h, m, tzinfo=SHANGHAI)
            self.assertTrue(due_slot(now.astimezone(timezone.utc)).endswith(f'T{h:02d}:{m:02d}+08:00'))
        self.assertIsNone(due_slot(datetime(2026, 11, 16, 9, 29, tzinfo=SHANGHAI)))
        self.assertIsNone(due_slot(datetime(2026, 11, 15, 15, tzinfo=SHANGHAI)))

    def test_restart_only_latest_slot_and_cooldown(self):
        now = datetime(2026, 11, 16, 14, tzinfo=SHANGHAI)
        slot = due_slot(now)
        self.assertTrue(slot.endswith('T13:00+08:00'))
        self.assertFalse(should_attempt({'last_success_slot': slot}, slot, now))
        self.assertFalse(should_attempt({'slot': slot, 'last_attempt_at': now.isoformat()}, slot, now))
        self.assertTrue(should_attempt({'slot': slot, 'last_attempt_at': (now-timedelta(minutes=11)).isoformat()}, slot, now))

    def test_long_failed_job_cools_down_from_completion(self):
        now = datetime(2026, 11, 16, 14, tzinfo=SHANGHAI)
        slot = due_slot(now)
        status = {'slot': slot, 'last_attempt_at': (now-timedelta(minutes=30)).isoformat(),
                  'last_finished_at': (now-timedelta(minutes=1)).isoformat()}
        self.assertFalse(should_attempt(status, slot, now))
        self.assertTrue(should_attempt(status, slot, now+timedelta(minutes=10)))

    def test_four_slots_persist_and_do_not_replay_on_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            client = Mock()
            client.get.return_value = {'data': {'item': [{'date': '20261116'}]}}
            def publish(_client, path, limit, slot):
                atomic_json(path / 'refresh_status.json', {'last_success_slot': slot})
            with patch('refresh_worker.run_refresh', side_effect=publish) as run:
                for hour, minute in [(9, 30), (11, 30), (13, 0), (15, 0)]:
                    now = datetime(2026, 11, 16, hour, minute, tzinfo=SHANGHAI)
                    self.assertEqual(tick(client, directory, now), 'updated')
                    self.assertEqual(read_json(directory / 'scheduler_status.json')['state'], 'updated')
                    self.assertEqual(tick(client, directory, now+timedelta(minutes=1)), 'already_done_or_cooldown')
                self.assertEqual(run.call_count, 4)
                self.assertEqual(client.get.call_count, 1)

    def test_corrupt_refresh_status_does_not_prevent_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / 'refresh_status.json').write_text('broken', encoding='utf-8')
            with patch('collect_data.collect_snapshot', side_effect=ApiError('unavailable')):
                with self.assertRaises(ApiError):
                    run_refresh(Mock(), directory)
            status = read_json(directory / 'refresh_status.json')
            self.assertEqual(status['state'], 'failed')
            self.assertIsNotNone(status['last_finished_at'])

    def test_holiday_not_treated_as_weekday_trading(self):
        with tempfile.TemporaryDirectory() as folder, patch('refresh_worker.run_refresh') as run:
            client = Mock()
            client.get.return_value = {'data': {'item': []}, 'request_id': 'holiday'}
            self.assertEqual(tick(client, Path(folder), datetime(2026, 10, 1, 10, tzinfo=SHANGHAI)), 'market_closed')
            run.assert_not_called()

    def test_calendar_failure_does_not_trigger_collection(self):
        with tempfile.TemporaryDirectory() as folder, patch('refresh_worker.run_refresh') as run:
            client = Mock()
            client.get.side_effect = ApiError('calendar unavailable')
            with self.assertRaises(ApiError):
                tick(client, Path(folder), datetime(2026, 11, 16, 10, tzinfo=SHANGHAI))
            run.assert_not_called()
            persisted = read_json(Path(folder) / 'scheduler_status.json')
            retry_time = datetime.fromisoformat(persisted['last_finished_at'])
            # Restart with the same slot should retain the calendar retry delay.
            with patch('refresh_worker.due_slot', return_value=persisted['slot']):
                self.assertEqual(tick(client, Path(folder), retry_time+timedelta(minutes=1)), 'already_done_or_cooldown')
            self.assertEqual(client.get.call_count, 1)

    def test_snapshot_change_rejects_inconsistent_comparison(self):
        with patch('app.load_snapshot', return_value={'metadata': {'snapshot_id': 'new'}, 'stocks': []}):
            with self.assertRaises(HTTPException) as caught:
                compare(CompareRequest(before=ScreenParams(pe_max=20), after=ScreenParams(pe_max=30), snapshot_id='a'*32))
            self.assertEqual(caught.exception.status_code, 409)

    def test_latest_snapshot_precedes_newer_legacy_file(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'STOCKLENS_DATA_DIR': folder, 'STOCKLENS_SNAPSHOT': ''}):
            latest = Path(folder) / 'stock_snapshot_latest.json'
            latest.write_text('{}')
            (Path(folder) / 'stock_snapshot_5.json').write_text('{}')
            self.assertEqual(snapshot_path(), latest)

    def test_adjustment_and_comparison_keep_original_snapshot(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'STOCKLENS_DATA_DIR': folder, 'STOCKLENS_SNAPSHOT': ''}):
            directory = Path(folder)
            identity = 'a'*32
            original = {'metadata': {'snapshot_id': identity}, 'stocks': [{'thscode': 'A', 'pe_ttm': 25}]}
            atomic_json(directory / 'history' / f'{identity}.json', original)
            atomic_json(directory / 'stock_snapshot_latest.json', original)
            first = screen(ScreenRequest(pe_max=20))
            atomic_json(directory / 'stock_snapshot_latest.json', {
                'metadata': {'snapshot_id': 'b'*32}, 'stocks': [{'thscode': 'A', 'pe_ttm': 100}]})
            pinned = screen(ScreenRequest(pe_max=30, snapshot_id=first['snapshot_metadata']['snapshot_id']))
            self.assertEqual(pinned['summary']['selected'], 1)
            diff = compare(CompareRequest(before=ScreenParams(pe_max=20), after=ScreenParams(pe_max=30), snapshot_id=identity))
            self.assertEqual(diff['changes']['newly_selected'][0]['thscode'], 'A')
            latest = screen(ScreenRequest(pe_max=30))
            self.assertEqual(latest['summary']['selected'], 0)
            self.assertEqual(latest['snapshot_metadata']['snapshot_id'], 'b'*32)
            with self.assertRaises(HTTPException) as caught:
                screen(ScreenRequest(pe_max=30, snapshot_id='c'*32))
            self.assertEqual(caught.exception.status_code, 409)

    def test_snapshot_identifier_cannot_escape_history_directory(self):
        from pydantic import ValidationError
        for identity in ['../stock_snapshot_latest', '', 'A'*32, 'a'*33]:
            with self.subTest(identity=identity), self.assertRaises(ValidationError):
                ScreenRequest(pe_max=20, snapshot_id=identity)


if __name__ == '__main__':
    unittest.main()
