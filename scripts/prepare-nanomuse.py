"""Apply the small, version-pinned Edith overlay to a nanoMuse source checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

REVISION = "09850259cab00d27af83786f00faa09b5d8494bf"
ROOT = Path(__file__).resolve().parents[1]


def prepare(checkout):
    checkout = Path(checkout).resolve()
    revision = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    if revision != REVISION:
        raise SystemExit("nanoMuse revision differs; review the overlay before updating")
    plugin = checkout / "harness/dsh-nanomuse"
    manifest = plugin / ".edith-overlay.json"
    previous = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    changes = {
        "src/cloud.ts": [
            ("import { TaskRunner, textOf }", "import { configuredBridge } from './edith-bridge.ts'\nimport { TaskRunner, textOf }"),
            ("      this.tasks = runner", """      this.tasks = runner
      const edith = configuredBridge({ runner,
        journalPath: join(dshHome(), 'nanomuse', 'edith-turns.json'),
        account: () => this.state.account?.id ?? '',
        status: () => ({ signed_in: this.signedIn, hub_connected: this.hub.connected,
          devices: this.hub.devices.map(d => ({ id: d.id, name: d.name, kind: d.kind, online: d.online })) }),
      })
      edith?.on('error', () => this.ctx.logger.warn('Edith bridge could not listen'))
      ctx.effect(() => () => edith?.close(), 'Edith glasses bridge')"""),
        ],
        "build.mjs": [("entryPoints: ['src/index.ts',", "entryPoints: ['src/edith-bridge.ts', 'src/index.ts',")],
        "src/task.ts": [
            ("    const stream = args.stream", """    const content: ContentBlock[] = [{ type: 'text', text: frame(from.name || from.id, this.options.deviceName(), text) }]
    // Edith: only the local glasses bridge can attach an explicitly requested camera frame.
    if (args.edith_image !== undefined) {
      if (from.id !== 'edith-glasses' || typeof args.edith_image !== 'string' || args.edith_image.length > 1_500_000 || !/^[A-Za-z0-9+/]+={0,2}$/.test(args.edith_image)) throw new HubError('usage', 'Invalid glasses image')
      const attachments = this.ctx.get('attachments')
      const llm = this.ctx.get('llm')
      const routed = agent.session.requestHeader()?.config
      const provider = routed?.provider ?? agent.options.provider
      const model = routed?.model ?? agent.options.model
      if (!attachments || !llm || !provider || !model) throw new HubError('failed', 'Image service unavailable')
      const info = await llm.resolveModelInfo(provider, model)
      if (!info.inputModalities?.includes('image')) throw new HubError('failed', 'Choose an image-capable model for glasses')
      const [attachment] = await attachments.saveImages([{ data: new Uint8Array(Buffer.from(args.edith_image, 'base64')), mediaType: 'image/jpeg', name: 'Edith requested camera frame' }])
      if (!attachment) throw new HubError('failed', 'Could not save glasses image')
      content.push({ type: 'image', attachment })
    }
    if (from.id === 'edith-glasses' && typeof args.edith_cancelled === 'function' && args.edith_cancelled()) throw new HubError('cancelled', 'Cancelled while preparing image')
    const stream = args.stream"""),
            ("content: [{ type: 'text', text: frame(from.name || from.id, this.options.deviceName(), text) }], source:", "content, source:"),
        ],
    }
    # Validate all anchors before writing anything; a second run is a no-op.
    outputs = {}
    for filename, replacements in changes.items():
        path = plugin / filename
        original = subprocess.check_output(["git", "-C", str(checkout), "show",
            REVISION + ":harness/dsh-nanomuse/" + filename]).decode("utf-8")
        text = original
        for before, after in replacements:
            if text.count(before) != 1:
                raise SystemExit(f"Overlay anchor mismatch: {filename}")
            text = text.replace(before, after)
        existing = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(existing.encode()).hexdigest()
        if existing not in {original, text} and digest != previous.get(filename):
            raise SystemExit(f"Unrecognized local edits; preserve and review: {filename}")
        outputs[path] = text
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8", newline="\n")
    shutil.copyfile(ROOT / "integrations/nanomuse/edith-bridge.ts", plugin / "src/edith-bridge.ts")
    manifest.write_text(json.dumps({str(p.relative_to(plugin)).replace('\\', '/'):
        hashlib.sha256(t.encode()).hexdigest() for p, t in outputs.items()}), encoding="utf-8")
    print("Edith overlay prepared for nanoMuse " + REVISION[:12])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("checkout")
    prepare(parser.parse_args().checkout)
