'use strict';
// One finite animation per event. Turning motion off cancels every active clock.
window.WednesdayMotion=(()=>{
  const running=new Set(),versions=new WeakMap(),media=matchMedia('(prefers-reduced-motion: reduce)');
  const reduced=()=>media.matches||document.documentElement.dataset.reduceMotion==='true';
  function settle(){if(reduced())for(const animation of running)animation.cancel();}
  function animate(node,frames,duration=220){
    if(!node)return Promise.resolve();versions.set(node,(versions.get(node)||0)+1);if(reduced()||!node.animate)return Promise.resolve();
    node.getAnimations().forEach(animation=>animation.cancel());
    const animation=node.animate(frames,{duration,easing:'cubic-bezier(.2,.8,.2,1)',fill:'none'});
    running.add(animation);
    return animation.finished.catch(()=>{}).finally(()=>running.delete(animation));
  }
  const enter=node=>{node?.getAnimations().forEach(animation=>animation.cancel());const base=node?getComputedStyle(node).transform:'none',transform=base==='none'?'':base;return animate(node,[{opacity:.35,transform:transform+' translateY(8px)'},{opacity:1,transform:transform+' translateY(0)'}]);};
  const pulse=node=>animate(node,[{transform:'scale(.96)',opacity:.7},{transform:'scale(1.045)',opacity:1,offset:.55},{transform:'scale(1)',opacity:1}],420);
  async function close(dialog){if(!dialog.open)return;const done=animate(dialog,[{opacity:1,transform:'translateY(0) scale(1)'},{opacity:0,transform:'translateY(5px) scale(.99)'}],120),version=versions.get(dialog);await done;if(dialog.open&&versions.get(dialog)===version)dialog.close();}
  media.addEventListener('change',settle);
  new MutationObserver(settle).observe(document.documentElement,{attributes:true,attributeFilter:['data-reduce-motion']});
  return {reduced,animate,enter,pulse,close,settle};
})();
