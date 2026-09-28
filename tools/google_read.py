from tools.registry import Risk, Tool
from tools.integrations import _connector_call


def register(registry, adapters=None):
    adapters=adapters or {}
    drive=adapters.get('drive')
    if drive is not None:
        registry.register(Tool('drive_list_files','List Google Drive files read-only; params: query',lambda p:_connector_call(drive,'list_all',str(p.get('query',''))[:1000]),Risk.READ_ONLY,connector_id='drive',capability='drive.files.list'))
        registry.register(Tool('drive_search_files','Search Google Drive files read-only; params: query',lambda p:_connector_call(drive,'list_all',str(p.get('query',''))[:1000]),Risk.READ_ONLY,connector_id='drive',capability='drive.files.search'))
        registry.register(Tool('drive_file_metadata','Read Google Drive file metadata; params: file_id',lambda p:_connector_call(drive,'get_metadata',str(p['file_id'])),Risk.READ_ONLY,connector_id='drive',capability='drive.files.metadata'))
        def drive_read(p):
            item=_connector_call(drive,'read_file',str(p['file_id']),export_mime=str(p.get('export_mime','text/plain')));content=item.pop('content',b'')
            if item.get('media_type') not in {'text/plain','text/csv','application/json'}:raise ValueError('Binary Drive content must be explicitly ingested into Knowledge before model use')
            try:text=content.decode('utf-8-sig')
            except Exception:raise ValueError('Drive text content could not be decoded safely')
            if len(text)>200000:raise ValueError('Drive text preview exceeds the 200,000 character tool limit; ingest it into Knowledge instead')
            return {**item,'text':text,'content_bytes':len(content)}
        registry.register(Tool('drive_read_file','Read an owner-selected textual Drive file without modifying it; params: file_id,export_mime',drive_read,Risk.READ_ONLY,connector_id='drive',capability='drive.files.read',prohibited_data_classifications=('secret',)))
    sheets=adapters.get('sheets')
    if sheets is not None:
        registry.register(Tool('sheets_spreadsheet_metadata','Read Google Sheets spreadsheet metadata; params: spreadsheet_id',lambda p:_connector_call(sheets,'spreadsheet_metadata',str(p['spreadsheet_id'])),Risk.READ_ONLY,connector_id='sheets',capability='sheets.spreadsheets.metadata'))
        registry.register(Tool('sheets_list_worksheets','List worksheets in a Google spreadsheet; params: spreadsheet_id',lambda p:_connector_call(sheets,'list_worksheets',str(p['spreadsheet_id'])),Risk.READ_ONLY,connector_id='sheets',capability='sheets.worksheets.list'))
        registry.register(Tool('sheets_read_values','Read a bounded Google Sheets A1 range; params: spreadsheet_id,range,value_mode',lambda p:_connector_call(sheets,'read_values',str(p['spreadsheet_id']),str(p['range']),value_mode=str(p.get('value_mode','formatted'))),Risk.READ_ONLY,connector_id='sheets',capability='sheets.values.read',prohibited_data_classifications=('secret',)))
        registry.register(Tool('sheets_batch_read_values','Read up to 10 bounded Google Sheets ranges; params: spreadsheet_id,ranges,value_mode',lambda p:_connector_call(sheets,'batch_read',str(p['spreadsheet_id']),list(p.get('ranges') or []),value_mode=str(p.get('value_mode','formatted'))),Risk.READ_ONLY,connector_id='sheets',capability='sheets.values.batch_read',prohibited_data_classifications=('secret',)))
