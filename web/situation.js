let mapPlace=null;
let interactiveMap=null,mapMarker=null,activeMapLayer='streets',mapLayers=null;
function setMapLayer(name){
 activeMapLayer=name;
 $('map-streets').setAttribute('aria-pressed',String(name==='streets'));$('map-satellite').setAttribute('aria-pressed',String(name==='satellite'));
 if(!interactiveMap)return;
 for(const layer of Object.values(mapLayers))interactiveMap.removeLayer(layer);
 mapLayers[name].addTo(interactiveMap);
}
$('map-streets').onclick=()=>setMapLayer('streets');$('map-satellite').onclick=()=>setMapLayer('satellite');
function selectMapPlace(place){
 mapPlace=place;$('map-place-title').textContent=place.name;
 const lat=place.lat,lon=place.lon;
 $('live-map').hidden=false;$('map-empty').hidden=true;
 if(!interactiveMap){
  interactiveMap=L.map('live-map',{zoomControl:true});
  mapLayers={streets:L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}),satellite:L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Tiles &copy; Esri — Sources: Esri, Maxar, Earthstar Geographics, and the GIS User Community'})};
  setMapLayer(activeMapLayer);
 }
 interactiveMap.invalidateSize();interactiveMap.setView([lat,lon],14);
 if(mapMarker)interactiveMap.removeLayer(mapMarker);
 mapMarker=L.circleMarker([lat,lon],{radius:8,color:'#ffffff',weight:2,fillColor:'#7c5cff',fillOpacity:1}).addTo(interactiveMap);
 const label=document.createElement('span');label.textContent=place.name;mapMarker.bindPopup(label);
 $('map-open').href=`https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=14/${lat}/${lon}`;$('map-open').hidden=false;
}
async function findMapPlace(query){
 $('map-search-button').disabled=true;$('map-home').disabled=true;$('map-status').textContent='Locating place…';
 try{const result=await api('/api/map',{query},20000);$('map-matches').replaceChildren();
 if(!result.places.length){$('map-status').textContent='No match found. Add a city or country to your search.';return;}
 for(const place of result.places){const button=document.createElement('button');button.className='quiet map-match';button.textContent=place.name;button.onclick=()=>selectMapPlace(place);$('map-matches').append(button);}
 selectMapPlace(result.places[0]);$('map-status').textContent=`${result.places.length} match${result.places.length===1?'':'es'} · select the correct place below`;
 }catch(error){$('map-status').textContent=error.message;}finally{$('map-search-button').disabled=false;$('map-home').disabled=false;}
}
$('map-form').onsubmit=event=>{event.preventDefault();findMapPlace($('map-query').value);};
$('map-home').onclick=()=>{if(searchLocation.mode==='off'||!searchLocation.city){$('map-status').textContent='Set a city in chat Location settings, or enter a place above.';return;}$('map-query').value=searchLocation.city;findMapPlace(searchLocation.city);};
document.querySelectorAll('[data-map-topic]').forEach(button=>button.onclick=()=>{if(!mapPlace){$('map-status').textContent='Choose an area first.';return;}showView('assistant');$('web-search').checked=true;$('input').value=`Find ${button.dataset.mapTopic} in ${mapPlace.name}. Summarize the best options using sources.`;$('input').focus();});
