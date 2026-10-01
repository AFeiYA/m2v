/** Static end-state composition. Word references remain usable by future entrance motion. */
export type PosterText = {id:string;text:string;word_indices:number[];x:number;y:number;width:number;height:number;size:number;weight:number;color:string};
export type PosterPlan = {version:'motion-poster-v1';aspect:'16:9';text:string;background:string;accent:string;nodes:PosterText[]};
export const rabbitPoster:PosterPlan = {
  version:'motion-poster-v1',aspect:'16:9',text:'欢迎来到　我的兔子洞　这里没有　所谓的成功',background:'#eeeee6',accent:'#c1ee47',
  nodes:[
    {id:'welcome',text:'欢迎来到',word_indices:[0,1,2,3],x:.075,y:.11,width:.5,height:.105,size:.077,weight:600,color:'#242923'},
    {id:'my',text:'我的',word_indices:[4,5],x:.079,y:.265,width:.21,height:.07,size:.05,weight:600,color:'#697263'},
    {id:'rabbit-hole',text:'兔子洞',word_indices:[6,7,8],x:.065,y:.345,width:.81,height:.28,size:.258,weight:900,color:'#20261e'},
    {id:'denial',text:'这里没有',word_indices:[9,10,11,12],x:.54,y:.70,width:.385,height:.085,size:.066,weight:600,color:'#536246'},
    {id:'success',text:'所谓的成功',word_indices:[13,14,15,16,17],x:.415,y:.805,width:.51,height:.11,size:.091,weight:800,color:'#20261e'},
  ],
};
const FONT='"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif';
export function drawPoster(canvas:HTMLCanvasElement,plan:PosterPlan=rabbitPoster) {
  const c=canvas.getContext('2d');if(!c)throw new Error('当前浏览器无法绘制海报');
  const W=canvas.width,H=canvas.height;
  c.clearRect(0,0,W,H);c.fillStyle=plan.background;c.fillRect(0,0,W,H);
  // Flat doorway motif: the lyric's rabbit hole is expressed without perspective effects.
  c.fillStyle=plan.accent;c.beginPath();c.ellipse(W*.805,H*.285,W*.10,H*.177,-.20,0,Math.PI*2);c.fill();
  c.strokeStyle='#a6b697';c.lineWidth=W*.001;
  for(let i=0;i<3;i++){c.beginPath();c.ellipse(W*.805,H*.285,W*(.10+i*.016),H*(.177+i*.028),-.20,0,Math.PI*2);c.stroke();}
  c.fillStyle='#20261e';c.fillRect(W*.075,H*.066,W*.065,H*.008);
  c.strokeStyle='#b8beb0';c.beginPath();c.moveTo(W*.075,H*.66);c.lineTo(W*.925,H*.66);c.stroke();
  const bounds=[];
  c.textBaseline='middle';c.textAlign='left';
  for(const node of plan.nodes){
    let size=node.size*H;
    const setFont=()=>{c.font=`${node.weight} ${size}px ${FONT}`;};setFont();
    const initial=c.measureText(node.text);
    const glyphHeight=initial.actualBoundingBoxAscent+initial.actualBoundingBoxDescent;
    size*=Math.min(1,node.width*W/Math.max(1,initial.width),node.height*H/Math.max(1,glyphHeight));setFont();
    const m=c.measureText(node.text),height=m.actualBoundingBoxAscent+m.actualBoundingBoxDescent;
    const y=node.y*H+(node.height*H-height)/2+m.actualBoundingBoxAscent;
    c.fillStyle=node.color;c.fillText(node.text,node.x*W,y);
    bounds.push({id:node.id,x:node.x*W,y:y-m.actualBoundingBoxAscent,width:m.width,height});
  }
  return bounds;
}
