"""Build a local reviewer archive from an explicit file allowlist."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT.parent
DIRECTORIES = {
    'src': {'.py', '.html', '.css', '.js'}, 'tests': {'.py'}, 'scripts': {'.py'},
    'policies': {'.pdf'}, 'docs': {'.md'},
    'examples': {'.py', '.json', '.md'}, 'test_set': {'.json'},
    'evaluation': {'.json', '.md', '.html', '.csv'},
}
FILES = ('README.md', 'SYSTEM_EXPLANATION_AND_TESTING_GUIDE.md', 'pyproject.toml',
         'uv.lock', '.gitignore', '.env.example', '.python-version')
TOP_LEVEL_FILES = (
    'AI_Claims_Agent_Implementation_Plan.md',
    'AI_Claims_Agent_Collaborative_Coding_Prompt.md',
    'AI_Engineer_Take_Home_Task.pdf',
    'Example_Policy_Document_HorizonCare.pdf',
)


def build():
    paths = [ROOT / name for name in FILES if (ROOT / name).exists()]
    for directory, extensions in DIRECTORIES.items():
        if not (ROOT / directory).exists():
            continue
        paths.extend(p for p in (ROOT / directory).rglob('*')
                     if p.is_file() and p.suffix in extensions
                     and not any(part.startswith('.') or part == '__pycache__'
                                 or part.endswith('.egg-info')
                                 for part in p.relative_to(ROOT).parts))
    output = ROOT / 'dist' / 'claims-agent.zip'
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            if path.is_symlink():
                raise ValueError('Submission files must not be symlinks')
            archive.write(path, Path('claims-agent') / path.relative_to(ROOT))
        for top_name in TOP_LEVEL_FILES:
            top_path = PARENT / top_name
            if top_path.exists():
                archive.write(top_path, top_name)
    print(f'Created {output.name}: {len(paths) + len(TOP_LEVEL_FILES)} files; credentials and local state excluded.')
    return output


if __name__ == '__main__':
    build()
