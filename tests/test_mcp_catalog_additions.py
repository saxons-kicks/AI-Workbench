import json
import tempfile
import unittest
from pathlib import Path

from aiwh.mcp_plan import mcp_plan


class McpCatalogAdditionsTests(unittest.TestCase):
    def test_ai_automation_plan_includes_codegraph_and_serena(self):
        with tempfile.TemporaryDirectory() as d:
            plan = mcp_plan(d, areas=['ai-automation'], windows=False)
            self.assertIn('codegraph', plan['mcps'])
            self.assertIn('serena', plan['mcps'])
            self.assertFalse(plan['applied'])
            self.assertEqual(list(Path(d).iterdir()), [])
            manual = {m['mcp'] for m in plan['manual_setup']}
            self.assertIn('serena', manual)
            self.assertNotIn('serena', plan['configured'])
            if 'codegraph' in plan['configured']:
                self.assertIn('codegraph', json.loads(plan['snippet'])['mcpServers'])


if __name__ == '__main__':
    unittest.main()
