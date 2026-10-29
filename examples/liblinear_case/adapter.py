"""ArtiCheck adapter, not author code. Run only in the rebuilt case container."""
import bz2
import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path


def save(name, value):
    Path(name).write_text(json.dumps(value, indent=2))


def main():
    stage, config_path = sys.argv[1:]
    cfg = json.loads(Path(config_path).read_text())
    if stage == 'prepare':
        with bz2.open('/artifact/news20.binary.bz2', 'rt') as source:
            rows = source.read().splitlines()
        if len(rows) != 19996:
            raise ValueError('Dataset instance count changed')
        # Split seeds are our explicit reconstruction, not the unpublished author split.
        indices = list(range(len(rows)))
        random.Random(cfg['seed']).shuffle(indices)
        test_ids, train_ids = indices[:4000], indices[4000:]
        for name, ids in [('train', train_ids), ('test', test_ids)]:
            Path(name+'.svm').write_text('\n'.join(rows[i] for i in ids)+'\n')
            Path(name+'.ids').write_text('\n'.join(map(str, ids))+'\n')
        save('split-provenance.json', {'source_sha256': hashlib.sha256(Path('/artifact/news20.binary.bz2').read_bytes()).hexdigest(),
             'seed': cfg['seed'], 'train_n': len(train_ids), 'test_n': len(test_ids),
             'protocol': 'Python random.Random(seed).shuffle row indices; first 4000 test',
             'author_split_recovered': False})
    elif stage == 'train':
        settings = cfg['variant']['settings']
        command = ['/opt/liblinear/train', '-s', str(settings['solver']), '-c', str(settings['C']),
                   '-e', str(cfg['hyperparameters']['epsilon']), '-q', 'train.svm', 'model.txt']
        subprocess.run(command, check=True)
        Path('used-config.json').write_text(Path(config_path).read_text())
        save('training-command.json', {'argv': command, 'split_seed': cfg['seed'], 'solver_random_seed': 'LIBLINEAR default; CLI does not expose seed'})
    elif stage == 'evaluate':
        subprocess.run(['/opt/liblinear/predict', 'test.svm', 'model.txt', 'predictions.txt'], check=True)
        truth = [float(line.split()[0]) for line in Path('test.svm').read_text().splitlines()]
        prediction = [float(line) for line in Path('predictions.txt').read_text().splitlines()]
        if len(truth) != len(prediction):
            raise ValueError('Prediction length mismatch')
        save('metrics.json', {'accuracy': sum(a == b for a,b in zip(truth,prediction))/len(truth), 'n': len(truth)})
        with Path('evaluation-records.jsonl').open('w') as out:
            for sample_id, target, predicted in zip(Path('test.ids').read_text().splitlines(), truth, prediction):
                out.write(json.dumps({'id': sample_id, 'target': target, 'prediction': predicted})+'\n')
    elif stage == 'summarize':
        save('summary.json', {'metrics': json.loads(Path('metrics.json').read_text()), 'scope': 'JMLR 2008 Section 3.1 reconstruction on news20; modern author revision; own declared splits',
                            'paper_comparison_figure_reproduced': False})
    else:
        raise ValueError('Unknown stage')


if __name__ == '__main__':
    main()
