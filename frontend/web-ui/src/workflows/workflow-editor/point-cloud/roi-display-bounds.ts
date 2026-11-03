import {Box3, Mesh, Vector3, type Object3D} from 'three'

/** 聚焦只使用已经绘制的有限网格及其裁切面，不用原云或测量算法。 */
export function expandRoiDisplayBounds(bounds:Box3,target:Object3D) {
  target.updateWorldMatrix(true,true)
  target.traverse(object=>{
    if(!(object instanceof Mesh)||Array.isArray(object.material))return
    const geometry=object.geometry,position=geometry.getAttribute('position'),index=geometry.index
    const planes=object.material.clippingPlanes??[]
    if(!planes.length){bounds.expandByObject(object);return}
    const count=index?index.count:position.count
    for(let i=0;i<count;i+=3){
      let polygon=Array.from({length:3},(_,j)=>new Vector3().fromBufferAttribute(position,index?index.getX(i+j):i+j).applyMatrix4(object.matrixWorld))
      for(const plane of planes){
        const clipped:Vector3[]=[]
        for(let j=0;j<polygon.length;j++){
          const a=polygon[j]!,b=polygon[(j+1)%polygon.length]!,da=plane.distanceToPoint(a),db=plane.distanceToPoint(b)
          if(da>=0)clipped.push(a)
          if((da<0)!==(db<0))clipped.push(a.clone().lerp(b,da/(da-db)))
        }
        polygon=clipped
        if(!polygon.length)break
      }
      for(const point of polygon)bounds.expandByPoint(point)
    }
  })
}
