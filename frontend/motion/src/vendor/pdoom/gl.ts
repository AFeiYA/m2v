/*! Adapted from mexicat/pdoom-video, Copyright (c) 2026 Giacomo Magnanini, MIT. See LICENSE. */
import * as THREE from 'three';
export const SCALE = 1;
export function makeRT(w: number, h: number, opts: THREE.RenderTargetOptions & {pxScale?:number} = {}) {
  const {pxScale: _, ...o} = opts;
  return new THREE.WebGLRenderTarget(Math.max(1,w), Math.max(1,h), {type:THREE.HalfFloatType, minFilter:THREE.LinearFilter, magFilter:THREE.LinearFilter, depthBuffer:false, ...o});
}
const COMMON = `
const vec3 C_BONE = vec3(0.85,0.83,0.76);
float sat(float x){return clamp(x,0.0,1.0);} vec3 sat(vec3 x){return clamp(x,0.0,1.0);}
float luma(vec3 c){return dot(c,vec3(0.2126,0.7152,0.0722));}
float hash12(vec2 p){vec3 p3=fract(vec3(p.xyx)*.1031);p3+=dot(p3,p3.yzx+33.33);return fract((p3.x+p3.y)*p3.z);}
vec3 toSRGB(vec3 c){return mix(12.92*c,1.055*pow(max(c,vec3(0.0)),vec3(1.0/2.4))-0.055,step(vec3(0.0031308),c));}
`;
export class FSPass {
  mat: THREE.RawShaderMaterial;
  scene = new THREE.Scene();
  cam = new THREE.OrthographicCamera(-1,1,1,-1,0,1);
  geom = new THREE.BufferGeometry();
  constructor(frag:string, uniforms:Record<string,THREE.IUniform>={}) {
    this.geom.setAttribute('position',new THREE.Float32BufferAttribute([-1,-1,0,3,-1,0,-1,3,0],3));
    this.mat=new THREE.RawShaderMaterial({glslVersion:THREE.GLSL3,
      vertexShader:'precision highp float; in vec3 position; out vec2 vUv; void main(){vUv=position.xy*0.5+0.5;gl_Position=vec4(position,1.0);}',
      fragmentShader:`precision highp float; precision highp int; in vec2 vUv; out vec4 fragColor; ${COMMON}\n${frag}`,
      uniforms,depthTest:false,depthWrite:false,blending:THREE.NoBlending});
    const mesh=new THREE.Mesh(this.geom,this.mat); mesh.frustumCulled=false; this.scene.add(mesh);
  }
  get u(){return this.mat.uniforms;}
  render(r:THREE.WebGLRenderer,target:THREE.WebGLRenderTarget|null){r.setRenderTarget(target);r.render(this.scene,this.cam);}
  dispose(){this.geom.dispose();this.mat.dispose();}
}
