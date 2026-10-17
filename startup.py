"""Recover saved services without blocking the web interface."""
import os
from pathlib import Path
import subprocess
import threading
import providers
import lm_studio

state = {'stage': 'starting', 'message': 'Checking saved connections…'}

def start():
    def work():
        try:
            provider, cfg = providers.config()
            if provider != 'local' or not cfg['model']:
                state.update(stage='ready', message='Connections restored.'); return
            state.update(stage='starting', message='Checking local AI…')
            try: models = lm_studio.call('models').get('models', [])
            except ValueError:
                if cfg['base_url'].rstrip('/') not in ('http://127.0.0.1:1234/v1','http://localhost:1234/v1'):
                    raise ValueError('Start your local model server, then reconnect in Setup.')
                cli = Path.home() / ('.lmstudio/bin/lms.exe' if os.name == 'nt' else '.lmstudio/bin/lms')
                if not cli.exists(): raise ValueError('LM Studio CLI is missing. Start its server in LM Studio.')
                state.update(message='Starting LM Studio…')
                result = subprocess.run([str(cli), 'server', 'start'], capture_output=True, timeout=60,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if result.returncode: raise ValueError('LM Studio could not start. Check it on your PC.')
                models = lm_studio.call('models').get('models', [])
            if any(i.get('id') == cfg['model'] for m in models for i in m.get('loaded_instances', [])):
                state.update(stage='ready', message='Local AI ready.'); return
            model = next((m for m in models if m.get('key') == cfg['model']), None)
            if not model:
                # OpenAI IDs sometimes differ from native model keys; never guess another model.
                raise ValueError('Select your downloaded model in Models, then load it. Saved model ID was not found.')
            state.update(message='Loading your selected model…')
            lm_studio.call('models/load', {'model': model['key'], 'context_length': min(32768, model.get('max_context_length',32768))})
            state.update(stage='ready', message='Local AI ready.')
        except (ValueError, OSError, subprocess.TimeoutExpired) as error:
            state.update(stage='attention', message=str(error))
    threading.Thread(target=work, daemon=True).start()
