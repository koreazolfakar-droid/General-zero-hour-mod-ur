"""Offline W3D geometry/UV preview; intentionally not an engine or gameplay test."""
import struct, math, json, argparse, tempfile, mmap, hashlib
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from big_archive import read_index
ROOT=Path(__file__).resolve().parents[1]
TEMP=tempfile.TemporaryDirectory(prefix='russian-visual-preview-')
WORK=Path(TEMP.name)
NEW=ROOT/'visuals/v1/Art/Textures'
LABELS=[('RBPwrPlnt','Power plant'),('RBBarracks','Barracks'),('RBComBnkr','Command center'),('RVKodiak','Kodiak')]
SHARED=[('RBIndstrial','Industrial plant (shared atlas)'),('RBWarfct','War factory (shared atlas)'),
        ('SCMRally','Russian waypoint marker (shared atlas)'),('RVBMD1','BMD (shared turret atlas)')]
HIDDEN={'RVKodiak':{'ARMOR01','ARMOR02','FIREPOINT01'},
        'RBComBnkr':{'RADAR','FLAGPART01','FLAGPART02','FLAGPART03','FAN01','FAN02','FAN03','FAN04'},
        'RBPwrPlnt':{'UPGRADE'}, 'SCMRally':{'BASE_USA','BASE_CHI','BASE_GLA','BASE_ECA'}}
def chunks(data):
    pos=0; result=[]
    while pos<len(data):
        kind,size=struct.unpack_from('<II',data,pos);size&=0x7fffffff
        result.append((kind,data[pos+8:pos+8+size]));pos+=8+size
    assert pos==len(data)
    return result
def only(items,kind):return next(data for k,data in items if k==kind)
def text(data):return data.split(b'\0',1)[0].decode('latin1')
def rotation(q):
    x,y,z,w=q
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                     [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                     [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
def model(name):
    top=chunks((WORK/(name+'.w3d')).read_bytes())
    transforms=[np.eye(4)]
    hier=next((d for k,d in top if k==0x100),None)
    if hier:
        raw=only(chunks(hier),0x102);transforms=[]
        for i in range(len(raw)//60):
            row=raw[i*60:(i+1)*60];parent=struct.unpack_from('<I',row,16)[0]
            local=np.eye(4);local[:3,3]=struct.unpack_from('<3f',row,20)
            local[:3,:3]=rotation(struct.unpack_from('<4f',row,44))
            transforms.append(local if parent==0xffffffff else transforms[parent]@local)
    bones={}
    hlod=next((d for k,d in top if k==0x700),None)
    if hlod:
        lod=only(chunks(hlod),0x702)
        for k,d in chunks(lod):
            if k==0x704:bones[text(d[4:]).upper()]=struct.unpack_from('<I',d)[0]
    hidden=HIDDEN.get(name,set())
    meshes=[]
    for k,data in top:
        if k!=0:continue
        items=chunks(data);hdr=only(items,0x1f)
        part=text(hdr[8:24]);container=text(hdr[24:40])
        if part.upper() in hidden or any(s in part.upper() for s in ('MUZZLE','MZZL','HEADLIGHT')):continue
        vertices=np.frombuffer(only(items,2),'<f4').reshape(-1,3).copy()
        tris=np.frombuffer(only(items,0x20),'<u4').reshape(-1,8)[:,:3]
        texture_names=[]
        for tk,td in chunks(only(items,0x30)):
            if tk==0x31:texture_names.append(text(only(chunks(td),0x32)))
        passes=[d for pk,d in items if pk==0x38]
        if not passes:continue
        stages=[d for pk,d in chunks(passes[0]) if pk==0x48]
        if not stages:continue
        stage=chunks(stages[0]);uv=np.frombuffer(only(stage,0x4a),'<f4').reshape(-1,2)
        ids=np.frombuffer(only(stage,0x49),'<u4')
        bone=bones.get((container+'.'+part).upper(),0)
        tr=transforms[bone]
        vertices=vertices@tr[:3,:3].T+tr[:3,3]
        meshes.append((part,vertices,tris,uv,ids,texture_names))
    return meshes
textures={}
cache={}
def texture(name,new):
    stem=Path(name).stem
    p=NEW/(stem+'.dds') if new else None
    if p is None or not p.exists():p=textures.get(stem.lower())
    if p is None:raise ValueError('Missing texture '+name)
    if str(p) not in cache:cache[str(p)]=np.array(Image.open(p).convert('RGBA'))
    return cache[str(p)]
def render(meshes,new,angle=0,size=700):
    eye=np.array([math.cos(angle),math.sin(angle),0.8]);eye/=np.linalg.norm(eye)
    right=np.cross([0,0,1],eye);right/=np.linalg.norm(right)
    up=np.cross(eye,right)
    camera=np.stack([right,-up,eye],axis=1)
    points=np.concatenate([v for _,v,*_ in meshes]);projected=points@camera
    lo=projected[:,:2].min(0);hi=projected[:,:2].max(0)
    scale=(size-85)/max(hi-lo);center=(lo+hi)*0.5
    canvas=np.empty((size,size,3),np.uint8);canvas[:]=[224,226,219]
    depth=np.full((size,size),-np.inf)
    sun=np.array([0.4,-0.6,0.85]);sun/=np.linalg.norm(sun)
    for part,v,tris,uv,ids,names in meshes:
        p=v@camera;p[:,:2]=(p[:,:2]-center)*scale+size/2
        for t,idx in enumerate(tris):
            tex_id=int(ids[0] if len(ids)==1 else ids[t])
            if tex_id==0xffffffff:continue
            name=names[tex_id]
            if any(x in name.lower() for x in ('lightbeam','muzzle','glow','exlnz')):continue
            tex=texture(name,new);h,w=tex.shape[:2]
            a,b,c=p[idx];xmin=max(0,int(np.floor(min(a[0],b[0],c[0]))));xmax=min(size-1,int(np.ceil(max(a[0],b[0],c[0]))))
            ymin=max(0,int(np.floor(min(a[1],b[1],c[1]))));ymax=min(size-1,int(np.ceil(max(a[1],b[1],c[1]))))
            if xmin>xmax or ymin>ymax:continue
            denom=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            if abs(denom)<1e-7:continue
            yy,xx=np.mgrid[ymin:ymax+1,xmin:xmax+1];xx=xx+0.5;yy=yy+0.5
            wa=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/denom
            wb=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/denom;wc=1-wa-wb
            z=wa*a[2]+wb*b[2]+wc*c[2]
            view=depth[ymin:ymax+1,xmin:xmax+1];mask=(wa>=-1e-5)&(wb>=-1e-5)&(wc>=-1e-5)&(z>view)
            if not mask.any():continue
            coord=wa[...,None]*uv[idx[0]]+wb[...,None]*uv[idx[1]]+wc[...,None]*uv[idx[2]]
            # Direct3D texture origin is the top left; repeat wraps animated tread UVs.
            tx=np.floor((coord[:,:,0]%1)*w).astype(int);ty=np.floor((coord[:,:,1]%1)*h).astype(int)
            pixels=tex[ty,tx].copy();mask &= pixels[:,:,3]>=128
            face=np.cross(v[idx[1]]-v[idx[0]],v[idx[2]]-v[idx[0]])
            shade=0.65+0.35*max(0,float(face@sun)/max(1e-7,np.linalg.norm(face)))
            rgb=np.clip(pixels[:,:,:3]*shade,0,255).astype(np.uint8)
            if 'housecolor' in name.lower():rgb=np.clip(rgb.astype(float)*[0.5,0.65,1.2],0,255).astype(np.uint8)
            canvas[ymin:ymax+1,xmin:xmax+1][mask]=rgb[mask];view[mask]=z[mask]
    return Image.fromarray(canvas)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shared',action='store_true',help='Preview additional models using the same seven textures')
    parser.add_argument('--output',type=Path,default=ROOT/'docs/visuals')
    args=parser.parse_args()
    labels=SHARED if args.shared else LABELS
    evidence=[]
    with (ROOT/'!ProjectXRe_Art.big').open('rb') as stream,mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as art:
        index={e.key:e for e in read_index(art)}
        needed=set()
        for name,_ in labels:
            e=index['art/w3d/'+name.lower()+'.w3d'];data=art[e.offset:e.offset+e.size]
            (WORK/(name+'.w3d')).write_bytes(data)
            evidence.append({'model':e.name,'sha256':hashlib.sha256(data).hexdigest()})
            for k,d in chunks(data):
                if k!=0:continue
                part=text(only(chunks(d),0x1f)[8:24]).upper()
                if part in HIDDEN.get(name,set()):continue
                for tk,td in chunks(d):
                    if tk==0x30:
                        for pk,pd in chunks(td):
                            if pk==0x31:
                                stem=Path(text(only(chunks(pd),0x32))).stem.lower()
                                if not any(x in stem for x in ('lightbeam','muzzle','glow','exlnz')):needed.add(stem)
        for stem in needed:
            e=index.get('art/textures/'+stem+'.dds') or index.get('art/textures/'+stem+'.tga')
            if e is None:raise ValueError('Missing source texture '+stem)
            p=WORK/(stem+Path(e.name).suffix.lower());p.write_bytes(art[e.offset:e.offset+e.size]);textures[stem]=p
    output=args.output
    output.mkdir(parents=True,exist_ok=True)
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',25)
    small=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',17)
    for view,angle in ([('shared',-2.2)] if args.shared else [('front',-2.2),('rear',0.8)]):
        sheet=Image.new('RGB',(1400,4*770+80),(244,245,240));draw=ImageDraw.Draw(sheet)
        draw.text((25,10),'Original',font=font,fill='#232723');draw.text((725,10),'Visuals v1',font=font,fill='#232723')
        for row,(name,label) in enumerate(labels):
            meshes=model(name)
            if view in ('front','shared'):
                for row_e in evidence:
                    if Path(row_e['model']).stem.lower()==name.lower():row_e['preview_triangles']=sum(len(m[2]) for m in meshes)
            for col,new in enumerate((False,True)):
                image=render(meshes,new,angle)
                sheet.paste(image,(col*700,75+row*770))
                draw.text((col*700+25,55+row*770),label,font=small,fill='#232723')
            print(view,name,sum(len(m[2]) for m in meshes),'triangles')
        draw.text((25,4*770+40),'Offline W3D + DDS preview. Simplified lighting; not a screenshot or device test.',font=small,fill='#232723')
        sheet.save(output/('comparison-'+view+'.jpg'),quality=92)
    (output/('preview-shared.json' if args.shared else 'preview-models.json')).write_text(json.dumps({
        'method':'Original W3D hierarchy base pose, first diffuse texture stage, UV coordinates and DDS alpha; simplified orthographic software lighting. No engine animation, particles, shadows or device execution.',
        'models':evidence},indent=2)+'\n')
