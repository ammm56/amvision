import type {CloudDisplayData} from './preview-data'

/** 每次选择只持有一个对照；迟到解码只能释放，不能重新安装。 */
export function createComparisonController(install:(value:CloudDisplayData|null)=>void,report:(error:string)=>void){
  let generation=0,controller:AbortController|null=null,data:CloudDisplayData|null=null,closed=false
  function clear(){generation++;controller?.abort();controller=null;install(null);data?.dispose();data=null}
  return {
    async load(decode:((signal:AbortSignal)=>Promise<CloudDisplayData>)|null){
      clear();report('');if(closed||!decode)return
      const token=generation;controller=new AbortController();const signal=controller.signal
      try{const result=await decode(signal);if(closed||signal.aborted||token!==generation){result.dispose();return}
        data=result;install(result)
      }catch(e){if(token===generation&&!signal.aborted&&!closed){install(null);data?.dispose();data=null;report(e instanceof Error?e.message:'cloud_preview_invalid')}}
    },
    dispose(){if(!closed){clear();closed=true}},
  }
}
