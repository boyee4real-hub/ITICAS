from __future__ import annotations
import math
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image, ImageDraw
from .map_proxy import tile as fetch_tile

TILE=256

def _world_px(lon:float, lat:float, z:int):
    lat=max(-85.05112878,min(85.05112878,float(lat)))
    n=2**int(z)
    x=(float(lon)+180.0)/360.0*n*TILE
    s=math.sin(math.radians(lat))
    y=(0.5-math.log((1+s)/(1-s))/(4*math.pi))*n*TILE
    return x,y

def _fetch(z,x,y):
    n=2**z
    x%=n
    if y<0 or y>=n:return None
    try:
        raw,mime,provider=fetch_tile(z,x,y)
        return x,y,Image.open(BytesIO(raw)).convert('RGB'),provider
    except Exception:
        return None

def render_static_map(lat:float,lon:float,zoom:int=6,width:int=1100,height:int=650):
    zoom=max(4,min(19,int(zoom))); width=max(480,min(1800,int(width))); height=max(320,min(1100,int(height)))
    cx,cy=_world_px(lon,lat,zoom)
    left=cx-width/2; top=cy-height/2
    tx0=math.floor(left/TILE); ty0=math.floor(top/TILE)
    tx1=math.floor((left+width-1)/TILE); ty1=math.floor((top+height-1)/TILE)
    canvas=Image.new('RGB',(width,height),(10,20,34)); providers=set(); jobs=[]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for ty in range(ty0,ty1+1):
            for tx in range(tx0,tx1+1):jobs.append(ex.submit(_fetch,zoom,tx,ty))
        for fut in as_completed(jobs):
            r=fut.result()
            if not r:continue
            tx,ty,img,provider=r;providers.add(provider)
            px=round(tx*TILE-left);py=round(ty*TILE-top);canvas.paste(img,(px,py))
    d=ImageDraw.Draw(canvas)
    d.rectangle((0,height-26,width, height),fill=(5,14,25))
    d.text((10,height-20),f"ITICAS basemap · {' / '.join(sorted(providers)) if providers else 'provider unavailable'}",fill=(220,235,245))
    out=BytesIO();canvas.save(out,'PNG',optimize=True)
    return out.getvalue(), ', '.join(sorted(providers)) if providers else 'unavailable'
