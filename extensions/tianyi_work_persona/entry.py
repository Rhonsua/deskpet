"""API-1 package. Work instructions are installed only on an explicit UI action."""
import json
from pathlib import Path


class TianyiWorkPersona:
    def __init__(self, context):
        self.context = context
        self.project = ''

    def start(self):
        self.context.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            saved = json.loads((self.context.data_dir / 'project.json').read_text('utf-8'))
            self.project = saved if isinstance(saved, str) else ''
        except (OSError, ValueError):
            self.project = ''

    def tick(self, now):
        pass

    def stop(self):
        pass

    def create_widget(self, parent=None):
        from .widget import PersonaWidget
        return PersonaWidget(self, parent)

    def remember(self, project):
        self.project = str(Path(project).resolve())
        path = self.context.data_dir / 'project.json'
        pending = path.with_suffix('.tmp')
        pending.write_text(json.dumps(self.project, ensure_ascii=False), encoding='utf-8')
        pending.replace(path)


factory = TianyiWorkPersona
