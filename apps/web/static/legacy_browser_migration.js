/* One-release migration boundary for preferences written by the predecessor UI. */
(function migrateLegacyBrowserState(){
  try {
    const oldPrefix='hermes';
    const keys=[];
    for(let index=0;index<localStorage.length;index+=1){
      const key=localStorage.key(index);
      if(key&&(key===oldPrefix||key.startsWith(oldPrefix+'-')||key.startsWith(oldPrefix+'.')||key.startsWith(oldPrefix+'_'))){
        keys.push(key);
      }
    }
    for(const oldKey of keys){
      const newKey='ares'+oldKey.slice(oldPrefix.length);
      if(localStorage.getItem(newKey)===null){
        const value=localStorage.getItem(oldKey);
        if(value!==null)localStorage.setItem(newKey,value);
      }
      localStorage.removeItem(oldKey);
    }
  } catch (_) {}
})();
