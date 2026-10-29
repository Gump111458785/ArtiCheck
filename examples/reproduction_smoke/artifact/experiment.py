import json, sys, random
from pathlib import Path
stage, cfg_path = sys.argv[1:]
cfg=json.loads(Path(cfg_path).read_text()); seed=cfg['seed'];variant=cfg['variant']['id']
if stage=='prepare':
    Path('prepared.json').write_text(Path(sys.argv[0]).with_name('data.json').read_text())
elif stage=='train':
    data=json.loads(Path('prepared.json').read_text());rng=random.Random(seed)
    rows=rng.choices(data['train'],k=len(data['train']))
    xs=[x for x,y in rows];ys=[y for x,y in rows];mx=sum(xs)/len(xs);my=sum(ys)/len(ys)
    slope=sum((x-mx)*(y-my) for x,y in rows)/sum((x-mx)**2 for x in xs) if variant!='baseline' else 0
    intercept=my-slope*mx if variant!='ablation' else 0
    Path('model.json').write_text(json.dumps({'slope':slope,'intercept':intercept}))
    Path('used-config.json').write_text(Path(cfg_path).read_text())
elif stage=='evaluate':
    model=json.loads(Path('model.json').read_text());data=json.loads(Path('prepared.json').read_text())
    error=sum((model['slope']*x+model['intercept']-y)**2 for x,y in data['test'])/len(data['test'])
    Path('metrics.json').write_text(json.dumps({'mse':error}))
