#!/usr/bin/env python3
"""Analyze locally verified Vigilia CI artifacts without contacting providers.

The native YAML report remains authoritative. This interface emits bounded JSON
summaries from the artifact bundles already downloaded with automation-workflow.
"""
import argparse
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

import yaml

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('vigilia_artifacts', ROOT / 'ci/download-artifacts.py')
artifacts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifacts)


def read_selection(directory, manifest_file):
    directory = directory.resolve()
    if not manifest_file.resolve().is_relative_to(directory):
        raise artifacts.ArtifactError('Manifest outside artifact directory')
    manifest = artifacts.artifact_verify(manifest_file)
    records = []
    for item in manifest['artifacts']:
        archive = manifest_file.parent / item['file']
        with zipfile.ZipFile(archive) as bundle:
            names = [n for n in bundle.namelist() if n.endswith('/report/report.yml')]
            if not names:
                records.append({'provider': item['provider'], 'profile': item['profile'],
                                'run_status': item['run_status'], 'job_status': item['job_status'],
                                'status': 'missing-report', 'errors': [], 'error_count': None,
                                'executed': None, 'discovered': None, 'duration_seconds': None})
                continue
            if len(names) > 1000:
                raise artifacts.ArtifactError('Too many report files in archive')
            for name in names:
                info = bundle.getinfo(name)
                if info.file_size > 32 * 1024 * 1024:
                    raise artifacts.ArtifactError('Native report exceeds size limit')
                report = yaml.safe_load(bundle.read(info))
                if not isinstance(report, dict):
                    raise artifacts.ArtifactError('Malformed native Vigilia report')
                global_report = report.get('global') or {}
                counters = global_report.get('test_counters') or {}
                errors = []
                for key, error in (report.get('errors') or {}).get('error_reports', {}).items():
                    errors.append({
                        'id': key,
                        'module': error.get('module_name'),
                        'description': error.get('description'),
                        'error': error.get('error'),
                        'command': error.get('executed_command'),
                    })
                start = global_report.get('time_start')
                end = global_report.get('time_end')
                try:
                    if isinstance(start, str):
                        start = datetime.fromisoformat(start)
                    if isinstance(end, str):
                        end = datetime.fromisoformat(end)
                    duration = round((end - start).total_seconds(), 3)
                except (TypeError, ValueError):
                    duration = None
                per_module = report.get('timings') or {}
                module_timings = []
                for module, timings in per_module.items():
                    if not isinstance(timings, dict):
                        continue
                    times = [v for v in timings.values() if isinstance(v, (float, int))]
                    module_timings.append({'module': module, 'assertion_seconds': round(sum(times), 3),
                                           'timed_assertions': len(times)})
                records.append({
                    'provider': item['provider'], 'profile': item['profile'],
                    'run_status': item['run_status'], 'job_status': item['job_status'],
                    'status': global_report.get('status'),
                    'error_count': global_report.get('error_count', len(errors)),
                    'errors': errors,
                    'executed': (counters.get('executed_totals') or {}).get('command_test'),
                    'discovered': (counters.get('discovered_totals') or {}).get('command_test'),
                    'duration_seconds': duration,
                    'module_timings': sorted(module_timings,
                                            key=lambda x: x['assertion_seconds'], reverse=True),
                    'report_path': name,
                })
    return {'revision': manifest['revision'], 'records': records}


def latest_manifest(directory):
    pointer = directory / 'latest.json'
    if not pointer.is_file():
        raise artifacts.ArtifactError(f'Missing latest artifact selection: {pointer}')
    latest = json.loads(pointer.read_text(encoding='utf-8'))
    sha = latest['revision']
    manifest = directory / latest['manifest']
    if not manifest.resolve().is_relative_to((directory / sha).resolve()):
        raise artifacts.ArtifactError('Unsafe latest manifest path')
    return manifest


def selections(directory, last):
    first = latest_manifest(directory)
    if last == 1:
        return [first]
    others = [p for p in directory.glob('*/manifest*.json') if p != first]
    # Metadata belongs to a previously downloaded revision, not the live API.
    others.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    distinct = {first.parent.name}
    chosen = [first]
    for path in others:
        if path.parent.name in distinct:
            continue
        distinct.add(path.parent.name)
        chosen.append(path)
        if len(chosen) >= last:
            break
    return chosen


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('results', 'failures', 'compare', 'timings'))
    parser.add_argument('--directory', type=Path, default=ROOT / 'ci-artifacts')
    parser.add_argument('--profile', choices=artifacts.PROFILES, default='full')
    parser.add_argument('--provider', action='append', choices=('github', 'gitlab'))
    parser.add_argument('--last', type=int, default=1, help='Recent distinct revisions (timings only)')
    parser.add_argument('--top', type=int, default=10, help='Slowest modules to show (timings only)')
    args = parser.parse_args(argv)
    if not 1 <= args.last <= 50 or not 1 <= args.top <= 100:
        parser.error('--last must be 1..50; --top must be 1..100')
    if args.command != 'timings' and (args.last != 1 or args.top != 10):
        parser.error('--last and --top are for timings')
    directory = args.directory.resolve()
    results = []
    for manifest in selections(directory, args.last if args.command == 'timings' else 1):
        selection = read_selection(directory, manifest)
        selection['records'] = [r for r in selection['records']
                                if r['profile'] == args.profile and
                                (not args.provider or r['provider'] in args.provider)]
        if selection['records']:
            results.append(selection)
    if not results:
        raise artifacts.ArtifactError('No matching report found in downloaded artifacts')
    if args.command == 'results':
        answer = results[0]
        for record in answer['records']:
            record.pop('module_timings', None)
            record.pop('errors', None)
    elif args.command == 'failures':
        answer = {'revision': results[0]['revision'], 'failures': [
            {'provider': r['provider'], 'profile': r['profile'],
             'run_status': r['run_status'], 'error_count': r['error_count'],
             'errors': r.get('errors', [])} for r in results[0]['records']
            if r['error_count'] or r['status'] == 'missing-report' or r['job_status'] not in ('success', 'available')]}
    elif args.command == 'compare':
        records = results[0]['records']
        answer = {'revision': results[0]['revision'], 'providers': {r['provider']: {
            'status': r['status'], 'run_status': r['run_status'],
            'executed': r['executed'], 'errors': r['error_count'],
            'duration_seconds': r['duration_seconds']} for r in records}}
        if len(answer['providers']) != 2:
            answer['note'] = 'Comparison requires both GitHub and GitLab in the selected bundle'
    else:
        answer = {'runs': []}
        for selection in results:
            answer['runs'].append({'revision': selection['revision'], 'providers': [
                {'provider': r['provider'], 'duration_seconds': r['duration_seconds'],
                 'slowest_modules': r.get('module_timings', [])[:args.top]}
                for r in selection['records']]})
    print(json.dumps(answer, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (artifacts.ArtifactError, OSError, ValueError, zipfile.BadZipFile, yaml.YAMLError) as exc:
        print(f'Report analysis failed: {exc}', file=sys.stderr)
        sys.exit(1)
