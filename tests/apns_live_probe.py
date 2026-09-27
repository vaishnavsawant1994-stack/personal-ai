from __future__ import annotations
import argparse,json,os
from core.config import settings
from notifications.apns import APNsProvider

def main():
    p=argparse.ArgumentParser();p.add_argument('--token',default=os.getenv('IOS_APNS_DEVICE_TOKEN',''));p.add_argument('--title',default='Personal AI');p.add_argument('--body',default='APNs production evidence test');a=p.parse_args()
    if not settings.apns_team_id or not settings.apns_key_id or not settings.apns_private_key_b64:raise SystemExit('APNs provider credentials are required')
    if not a.token:raise SystemExit('IOS_APNS_DEVICE_TOKEN is required')
    provider=APNsProvider(settings)
    try:result=provider.send_token(a.token,a.title,a.body,data={'kind':'production_evidence'})
    finally:provider.close()
    print(json.dumps(result.as_dict(),sort_keys=True))
    if not result.ok:raise SystemExit(f'APNs rejected push: {result.status} {result.reason}')
if __name__=='__main__':main()
