/** Shared, paginated song/version chooser. Callers provide their existing authenticated API. */
(function () {
  function mount(select, request, choose) {
    if (!select || select.dataset.songPicker) return;
    select.dataset.songPicker = 'ready';
    select.hidden = true;
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = 'Choose song & version';
    select.after(button);
    const dialog = document.createElement('dialog'); dialog.className = 'song-picker';
    dialog.innerHTML = '<form method="dialog"><strong>Your songs</strong><button aria-label="Close song chooser">Close</button></form><input type="search" aria-label="Search your songs" placeholder="Search song titles or artists"><p role="status"></p><div class="picker-list"></div><footer><button type="button" class="picker-prev">Previous</button><span></span><button type="button" class="picker-next">Next</button></footer>';
    document.body.append(dialog);
    const search=dialog.querySelector('input'), status=dialog.querySelector('[role=status]'), list=dialog.querySelector('.picker-list');
    const prev=dialog.querySelector('.picker-prev'), next=dialog.querySelector('.picker-next'), pageText=dialog.querySelector('footer span');
    let page=1, sequence=0, timer, busy=false;
    const account=()=>{
      try {
        const user=JSON.parse(localStorage.getItem('m2v_user')||'null');
        if(user?.id||user?.uid)return user.id||user.uid;
        const token=localStorage.getItem('m2v_token')||'';
        return JSON.parse(atob(token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))).sub||'';
      } catch {return '';}
    };
    let owner=account();
    const sameOwner=()=>{if(owner===account())return true;sequence++;dialog.close();return false;};
    window.addEventListener('storage',()=>{if(dialog.open)sameOwner();});
    dialog.addEventListener('close',()=>{sequence++;});
    async function load(value=1) {
      const order=++sequence; status.textContent='Loading songs…';
      try {
        const data=await request('/api/songs?view=all&page_size=12&page='+value+'&q='+encodeURIComponent(search.value));
        if(order!==sequence||!dialog.open||!sameOwner())return;
        page=value;list.replaceChildren();
        for(const song of data.songs){
          const item=document.createElement('section'), title=document.createElement('h3'), versions=document.createElement('select'), open=document.createElement('button');
          title.textContent=song.title+(song.artist?' · '+song.artist:'')+(song.archived?' · Archived':'');
          versions.setAttribute('aria-label',song.title+' lyric version');
          for(const v of song.versions.filter(v=>v.editable)){
            const option=document.createElement('option');option.value=v.id;
            option.textContent=(v.id===song.current_task_id?'Current · ':'')+v.title+' · '+new Date(v.updated_at).toLocaleString();
            versions.append(option);
          }
          if(song.current_task_id)versions.value=song.current_task_id;
          open.type='button';open.textContent='Open version';open.disabled=!versions.options.length;
          open.onclick=async()=>{
            if(busy||!sameOwner())return;busy=true;open.disabled=true;
            try {if(await choose(versions.value)!==false&&sameOwner()){button.textContent=song.title;dialog.close();}}
            catch(error){status.textContent=error.message;}
            finally{busy=false;open.disabled=!versions.options.length;}
          };
          item.append(title,versions,open);list.append(item);
        }
        status.textContent=data.total?data.total+(data.total===1?' song':' songs')+' · Choose a saved lyric version.':'No matching songs.';
        prev.disabled=page<=1;next.disabled=page*12>=data.total;pageText.textContent='Page '+page+' of '+Math.max(1,Math.ceil(data.total/12));
      }catch(error){if(order===sequence)status.textContent=error.message;}
    }
    button.onclick=()=>{owner=account();dialog.showModal();void load(1);};
    search.oninput=()=>{sequence++;clearTimeout(timer);timer=setTimeout(()=>load(1),250);};
    prev.onclick=()=>load(page-1);next.onclick=()=>load(page+1);
    return {setTitle:title=>{button.textContent=title||'Choose song & version';}};
  }
  window.m2vSongPicker={mount};
})();
