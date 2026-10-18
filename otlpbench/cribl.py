"""Start an isolated standalone Cribl Edge with local benchmark configuration."""
import os
from pathlib import Path
import sys
import yaml

if __name__ == '__main__':
    conf=yaml.safe_load(Path(sys.argv[1]).read_text())
    root=Path('/opt/cribl/local/cribl'); root.mkdir(parents=True,exist_ok=True)
    for filename,content in conf.items():
        path=root/filename; path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(yaml.safe_dump(content,sort_keys=False))
    os.environ['CRIBL_EDGE']='1'
    os.environ['CRIBL_HOME']='/opt/cribl'
    os.execv('/opt/cribl/bin/cribl',['/opt/cribl/bin/cribl','server'])
