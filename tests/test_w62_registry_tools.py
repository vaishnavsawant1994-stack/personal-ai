from types import SimpleNamespace
from integrations.contracts import builtin_manifests,drive_manifest,sheets_manifest
from integrations.registry import IntegrationRegistry
from tools.google_read import register
from tools.registry import ToolRegistry,Risk

def test_builtin_manifests_include_drive_sheets():
 ids={m.connector_id for m in builtin_manifests()};assert {'drive','sheets'}<=ids

def test_registry_exposes_read_only_missing_scopes(tmp_path):
 class State:
  def health(self,c):return {'state':'not_configured','granted_scopes':[],'revocation_status':'none'}
 r=IntegrationRegistry(state_store=State());r.register_manifest(drive_manifest());r.register_manifest(sheets_manifest());items={x['id']:x for x in r.list()};assert items['drive']['missing_scopes']==list(drive_manifest().required_oauth_scopes);assert not items['drive']['read_only'] and not items['sheets']['read_only'];assert any(not o['write_enabled'] for o in items['drive']['operations'] if o['effect']!='read')

def test_tools_register_drive_sheets_read_only(tmp_path):
 class D:
  gateway=None
  def list_all(self,q=''):return {'items':[]}
  def get_metadata(self,x):return {'id':x}
  def read_file(self,x,export_mime='text/plain'):return {'content':b'x','media_type':'text/plain','filename':'x.txt','provenance':{}}
 class S:
  gateway=None
  def spreadsheet_metadata(self,x):return {'spreadsheetId':x}
  def list_worksheets(self,x):return []
  def read_values(self,x,r,value_mode='formatted'):return {'values':[]}
  def batch_read(self,x,r,value_mode='formatted'):return {'value_ranges':[]}
 tr=ToolRegistry(SimpleNamespace(autonomy_mode='act',data_dir=tmp_path));register(tr,{'drive':D(),'sheets':S()});names={t.name for t in tr.all()};assert {'drive_list_files','drive_read_file','sheets_read_values','sheets_batch_read_values'}<=names;assert all(t.risk==Risk.READ_ONLY for t in tr.all())
