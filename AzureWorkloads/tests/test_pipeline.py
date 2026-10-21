import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from extract_azure import extract_archive


class ExtractionTests(unittest.TestCase):
    def test_rejects_paths_and_links_before_writing(self):
        for name, kind in [('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE),
                           ('link', tarfile.SYMTYPE), ('hard', tarfile.LNKTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                archive = Path(tmp) / 'bad.tar.xz'
                with tarfile.open(archive, 'w:xz') as tar:
                    safe = tarfile.TarInfo('safe.csv'); safe.size = 2
                    tar.addfile(safe, io.BytesIO(b'a\n'))
                    bad = tarfile.TarInfo(name); bad.type = kind; bad.linkname = '../escape'
                    tar.addfile(bad)
                output = Path(tmp) / 'output'
                with self.assertRaises(ValueError):
                    extract_archive(archive, output)
                self.assertFalse((output / 'safe.csv').exists())

    def test_extracts_regular_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / 'ok.tar.xz'
            with tarfile.open(archive, 'w:xz') as tar:
                member = tarfile.TarInfo('a/data.csv'); member.size = 4
                tar.addfile(member, io.BytesIO(b'a\n1\n'))
            result = extract_archive(archive, Path(tmp) / 'output')
            self.assertEqual((Path(tmp) / 'output/a/data.csv').read_text(), 'a\n1\n')
            self.assertEqual(len(result['files']), 1)

class CleaningTests(unittest.TestCase):
    def test_deduplicates_only_identical_records_and_flags_conflicts(self):
        import pandas as pd
        from clean_azure import clean_frame
        from common import KEY, STATS
        rows = [dict(zip(KEY, ['o', 'a', 'f']), **dict.fromkeys(STATS, 2)) for _ in range(3)]
        rows[2]['Average'] = 3
        frame, report, audit = clean_frame(pd.DataFrame(rows), 'duration', 1, 'test.csv')
        self.assertEqual(len(frame), 2)
        self.assertEqual(report['duplicates_dropped'], 1)
        self.assertTrue((frame.duration_status == 'conflicting_key').all())

    def test_preserves_zero_and_missing_counts_and_rejects_invalid_cells(self):
        import pandas as pd
        from clean_azure import clean_frame
        from common import KEY, MINUTES
        row = dict(zip(KEY, ['o', 'a', 'f']), Trigger='http', **dict.fromkeys(MINUTES, 0))
        row['2'] = None; row['3'] = -1; row['4'] = 1.5; row['5'] = float('inf')
        frame, report, audit = clean_frame(pd.DataFrame([row]), 'invocation', 1, 'test.csv')
        self.assertEqual(frame.iloc[0]['1'], 0)
        self.assertTrue(frame[['2','3','4','5']].isna().all().all())
        self.assertEqual(report['missing_cells'], 1)
        self.assertEqual(report['invalid_cells'], 3)

    def test_does_not_impute_zero_or_missing_duration(self):
        import pandas as pd
        from clean_azure import clean_frame
        from common import KEY, STATS
        row = dict(zip(KEY, ['o', 'a', 'f']), **dict.fromkeys(STATS, 2))
        row['Average'] = 0; row['Minimum'] = None
        frame, report, audit = clean_frame(pd.DataFrame([row]), 'duration', 1, 'test.csv')
        self.assertEqual(frame.Average.iloc[0], 0)
        self.assertEqual(frame.duration_status.iloc[0], 'nonpositive_or_missing_mean')
        self.assertTrue(frame.Minimum.isna().all())

class ConversionTests(unittest.TestCase):
    def test_seeded_arrivals_preserve_every_count_and_quiet_minute(self):
        from convert_workloads import reconstruct
        source = dict(day=3, source_row=7, duration_row=8, HashOwner='o', HashApp='a',
                      HashFunction='f', Average=2.25, Trigger='http', counts=[2,0,3], start_minute=60)
        first = reconstruct('w', [source], 42)
        self.assertEqual(first, reconstruct('w', [source], 42))
        self.assertNotEqual(first, reconstruct('w', [source], 43))
        self.assertEqual(len(first), 5)
        self.assertEqual([sum(j['source_minute'] == m for j in first) for m in [61,62,63]], [2,0,3])
        for job in first:
            self.assertEqual(job['burst_time'], 3)
            self.assertEqual(job['priority'], 0)
            self.assertEqual(job['absolute_arrival_time'], 2*86400000 + 60*60000 + job['arrival_time'])
            self.assertEqual(job['arrival_time']//60000 + 61, job['source_minute'])

    def test_ineligible_sources_are_rejected(self):
        from convert_workloads import reconstruct
        base = dict(day=1, source_row=2, duration_row=2, HashOwner='o', HashApp='a',
                    HashFunction='f', Average=1, Trigger='http', counts=[1], start_minute=0)
        for updates in [dict(Average=0),dict(Average=float('nan')),dict(counts=[-1]),dict(counts=[None]),dict(counts=[1.5])]:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                reconstruct('w', [dict(base, **updates)], 42)

class EndToEndTests(unittest.TestCase):
    def test_pipeline_validates_and_detects_mutated_units_and_traceability(self):
        import json
        import pandas as pd
        import subprocess
        from common import KEY, MINUTES, STATS, INV_COLUMNS, DUR_COLUMNS
        from validate_azure import validate
        scripts = Path(__file__).resolve().parents[1] / 'scripts'
        repo = scripts.parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'extracted').mkdir(); (root/'reports').mkdir()
            for day in [1,2]:
                inv, dur = [], []
                for f in range(4):
                    ids = dict(zip(KEY,['o','a',f'f{f}']))
                    counts = dict.fromkeys(MINUTES,0)
                    for m in range(1,1441):
                        if (m+f) % 7 == 0:
                            counts[str(m)] = f+1
                    inv.append(dict(ids,Trigger=None if f==0 else 'http',**counts))
                    duration = dict(ids,**dict.fromkeys(STATS,f+1))
                    duration['Count'] = sum(counts.values()); dur.append(duration)
                pd.DataFrame(inv,columns=INV_COLUMNS).to_csv(root/f'extracted/invocations_per_function_md.anon.d{day:02}.csv',index=False)
                pd.DataFrame(dur,columns=DUR_COLUMNS).to_csv(root/f'extracted/function_durations_percentiles.anon.d{day:02}.csv',index=False)
            for script in ['clean_azure.py','convert_workloads.py']:
                completed = subprocess.run([sys.executable,str(scripts/script),'--root',str(root)],capture_output=True,text=True)
                self.assertEqual(completed.returncode,0,completed.stderr)
            result = validate(root,repo)
            self.assertTrue(result['passed']); self.assertGreater(result['scheduler_jobs'],0)
            path = root/'cleaned/evaluation_workloads.json'
            original = path.read_text(); payload = json.loads(original)
            payload['time_unit'] = 'seconds'; path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError,'time unit'):
                validate(root,repo)
            payload = json.loads(original)
            payload['workloads'][0]['sources'][0]['counts'][0] += 1
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError,'Minute counts'):
                validate(root,repo)


if __name__ == '__main__':
    unittest.main()
