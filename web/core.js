/* DreadOS AI core: perspective-projected orbital lattice, rendered locally. */
(() => {
  const canvas = document.getElementById('particle-core');
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  document.querySelector('.core-fallback').hidden = true;
  const parent = canvas.parentElement;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let width = 0, height = 0, pointerX = 0, pointerY = 0, frame, visible = true, speechEnergy = 0;
  let lastTime=0, phase=0, workLevel=0, searchLevel=0, readLevel=0;
  new ResizeObserver(entries => {
    const box = entries[0].contentRect; width = box.width; height = box.height;
    const dpr = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr,0,0,dpr,0,0);
    if (reduced.matches) draw(0);
  }).observe(parent);
  parent.addEventListener('pointermove', event => {
    const box = parent.getBoundingClientRect(); pointerX = (event.clientX-box.left)/box.width-.5; pointerY = (event.clientY-box.top)/box.height-.5;
  });
  parent.addEventListener('pointerleave', () => { pointerX=0; pointerY=0; });
  function draw(timestamp) {
    if (!width || !height) return;
    const time = reduced.matches ? 0 : timestamp * .00012;
    const active = parent.classList.contains('listening');
    const audio = typeof getVoiceEnergy==='function' ? getVoiceEnergy() : {level:0,bands:null};
    speechEnergy += (audio.level-speechEnergy)*(audio.level>speechEnergy?.55:.16);
    const energyLevel=reduced.matches?0:speechEnergy;
    parent.dataset.audioLevel=energyLevel.toFixed(3);
    const searching=parent.classList.contains('searching');
    const reading=parent.classList.contains('reading')||parent.classList.contains('analyzing');
    const thinking=parent.classList.contains('thinking')||parent.classList.contains('transcribing')||parent.classList.contains('compacting');
    const dt=Math.min(Math.max((timestamp-lastTime)/1000,0),.05);lastTime=timestamp;
    const blend=reduced.matches?1:1-Math.exp(-dt*5);
    workLevel+=((thinking||searching||reading?1:0)-workLevel)*blend;
    searchLevel+=((searching?1:0)-searchLevel)*blend;
    readLevel+=((reading?1:0)-readLevel)*blend;
    phase+=reduced.matches?0:dt*(.12+workLevel*.42+searchLevel*.35);
    const workPulse=reduced.matches?.5:(Math.sin(time*22)+1)/2;
    const size = Math.min(width * .29,height * .34);
    const pulse = 1 + Math.sin(time*(active ? 45 : 5))*(active ? .04 : .01) + energyLevel*.14 + workLevel*(.015+workPulse*.045);
    const spin = phase + pointerX*.28;
    const tilt = -.25 + pointerY*.3;
    ctx.clearRect(0,0,width,height);
    ctx.save(); ctx.translate(width/2,height/2-3);
    const glow = ctx.createRadialGradient(0,0,8,0,0,size*1.55);
    glow.addColorStop(0,`rgba(${thinking?'175,145,255':'110,225,255'},${.14+energyLevel*.42+workLevel*(.12+workPulse*.12)})`); glow.addColorStop(.48,'#6359ad20'); glow.addColorStop(1,'#151b3800');
    ctx.fillStyle=glow; ctx.fillRect(-width/2,-height/2,width,height);
    function project(x,y,z) {
      const rx=x*Math.cos(spin)-z*Math.sin(spin), rz=x*Math.sin(spin)+z*Math.cos(spin);
      const ry=y*Math.cos(tilt)-rz*Math.sin(tilt), depth=y*Math.sin(tilt)+rz*Math.cos(tilt);
      const scale=3.5/(3.5-depth);
      return [rx*size*scale*pulse,ry*size*scale*pulse,depth];
    }
    // A luminous inner field, with no central badge or lettering.
    ctx.globalCompositeOperation='lighter';
    const energy=ctx.createRadialGradient(0,0,0,0,0,size);
    energy.addColorStop(0,`rgba(183,250,255,${.28+energyLevel*.6})`);
    energy.addColorStop(.22,'#46ccff35');
    energy.addColorStop(.6,'#526fff12');
    energy.addColorStop(1,'#526fff00');
    ctx.fillStyle=energy;ctx.fillRect(-size,-size,size*2,size*2);
    // Fine wave contours wrap around the core like a holographic membrane.
    for(let band=0;band<34;band++) {
      const latitude=-1.44+band/33*2.88;
      const ringRadius=Math.cos(latitude);
      ctx.beginPath();
      for(let step=0;step<=100;step++) {
        const theta=step/100*Math.PI*2;
        const ripple=1+Math.sin(theta*6+latitude*8+phase*9)*(.025+(active?.025:0)+energyLevel*.065+workLevel*.035);
        const p=project(Math.cos(theta)*ringRadius*ripple,Math.sin(latitude)*.96,Math.sin(theta)*ringRadius*ripple);
        if(step===0)ctx.moveTo(p[0],p[1]);else ctx.lineTo(p[0],p[1]);
      }
      ctx.strokeStyle=`hsla(${188+band*2+workLevel*18-searchLevel*22},95%,73%,${.14+Math.sin(band/33*Math.PI)*.22+energyLevel*.28+workLevel*.13})`;
      ctx.lineWidth=(band%5===0?1:.55)+energyLevel*.6;ctx.stroke();
    }
    for(let i=0;i<900;i++) {
      const y=1-i/899*2,r=Math.sqrt(1-y*y),theta=i*2.399963;
      const flow=1+.035*Math.sin(y*12+theta*3+time*8);
      const p=project(Math.cos(theta)*r*flow,y,Math.sin(theta)*r*flow);
      ctx.fillStyle=`rgba(155,225,255,${.15+(p[2]+1)*.23})`;
      ctx.beginPath();ctx.arc(p[0],p[1],.45+(p[2]+1)*.28,0,7);ctx.fill();
    }
    // Three independently rotating, broken orbital tracks and travelling signals.
    for(let orbit=0;orbit<3;orbit++) {
      ctx.save();ctx.rotate([-.34,.65,-1.04][orbit]+Math.sin(time*.8)*.08);
      const rx=size*(1.34+orbit*.025),ry=size*(.43+orbit*.13);
      ctx.strokeStyle=orbit===1?'#b297ff55':'#75ddff66';ctx.lineWidth=.7;
      ctx.setLineDash([size*.12,size*.035,2,size*.035]);ctx.lineDashOffset=time*(orbit%2?18:-22);
      ctx.beginPath();ctx.ellipse(0,0,rx,ry,0,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);
      const angle=phase*1.8*(orbit%2?-1:1)+orbit*2;
      ctx.strokeStyle=orbit===1?'#c1a8ff':'#a3f2ff';ctx.lineWidth=1.7;
      ctx.shadowColor=ctx.strokeStyle;ctx.shadowBlur=12;
      ctx.beginPath();ctx.ellipse(0,0,rx,ry,0,angle,angle+.5);ctx.stroke();
      ctx.fillStyle='#e7fcff';ctx.beginPath();ctx.arc(Math.cos(angle+.5)*rx,Math.sin(angle+.5)*ry,2,0,7);ctx.fill();
      ctx.restore();
    }
    // Search sweeps outward; reading scans vertically through the lattice.
    if(searchLevel>.01){
      for(let ring=0;ring<3;ring++){
        const progress=reduced.matches?(ring+1)/4:(time*3+ring/3)%1;
        ctx.strokeStyle=`rgba(115,232,255,${searchLevel*(1-progress)*.5})`;
        ctx.lineWidth=1.2;ctx.beginPath();ctx.arc(0,0,size*(.35+progress*1.05),0,Math.PI*2);ctx.stroke();
      }
      const scan=phase*2.5;
      ctx.strokeStyle=`rgba(150,245,255,${searchLevel*.8})`;ctx.lineWidth=2;
      ctx.beginPath();ctx.arc(0,0,size*1.2,scan,scan+.8);ctx.stroke();
    }
    if(readLevel>.01){
      const y=(reduced.matches?0:Math.sin(time*9))*size*.85;
      const span=Math.sqrt(Math.max(0,size*size-y*y));
      ctx.strokeStyle=`rgba(196,165,255,${readLevel*.8})`;ctx.lineWidth=2;
      ctx.beginPath();ctx.moveTo(-span,y);ctx.lineTo(span,y);ctx.stroke();
    }
    // Instrument ticks and small scanning arcs frame the energy field.
    for(let tick=0;tick<96;tick++) {
      const angle=tick/96*Math.PI*2;
      const frequency=audio.bands?audio.bands[2+Math.floor((tick%48)/48*85)]/255:0;
      const r=size*1.17, length=(tick%8===0?6:2)+frequency*energyLevel*size*.22;
      ctx.strokeStyle=`rgba(150,235,255,${(tick%8===0?.5:.17)+energyLevel*.45})`;ctx.lineWidth=.7;
      ctx.beginPath();ctx.moveTo(Math.cos(angle)*r,Math.sin(angle)*r);
      ctx.lineTo(Math.cos(angle)*(r+length),Math.sin(angle)*(r+length));ctx.stroke();
    }
    ctx.strokeStyle='#88e9ff99';ctx.lineWidth=1;
    for(let arc=0;arc<2;arc++) {
      const start=-time*.45+arc*Math.PI;
      ctx.beginPath();ctx.arc(0,0,size*1.11,start,start+.45);ctx.stroke();
    }
    ctx.globalCompositeOperation='source-over';
    ctx.strokeStyle='#a4baff60';ctx.lineWidth=.6;
    for(const side of [-1,1]) {
      ctx.beginPath();ctx.moveTo(side*size*1.39,-size*.75);ctx.lineTo(side*size*1.39,-size*.91);
      ctx.lineTo(side*size*1.23,-size*.91);ctx.stroke();
      ctx.beginPath();ctx.moveTo(side*size*1.39,size*.75);ctx.lineTo(side*size*1.39,size*.91);
      ctx.lineTo(side*size*1.23,size*.91);ctx.stroke();
    }
    ctx.restore();
  }
  function animate(time) { if(!visible)return;draw(time);if(!reduced.matches)frame=requestAnimationFrame(animate); }
  function restart() { cancelAnimationFrame(frame);if(visible)frame=requestAnimationFrame(animate); }
  document.addEventListener('visibilitychange',()=>{visible=!document.hidden;restart();});
  reduced.addEventListener('change',restart);
  new MutationObserver(()=>{if(reduced.matches)draw(0);}).observe(parent,{attributes:true,attributeFilter:['class']});
  new IntersectionObserver(entries=>{visible=entries[0].isIntersecting&&!document.hidden;restart();}).observe(canvas);
})();
