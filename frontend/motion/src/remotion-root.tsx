import React,{useMemo} from 'react';
import {Composition,registerRoot} from 'remotion';
import {LyricVideo,type VideoProps} from './lyric-video';
import {demo,defaults,renderSize,normalizeProject} from './model';
const NormalizedVideo:React.FC<VideoProps>=(props)=>{const project=useMemo(()=>normalizeProject(props.project),[props.project]);return <LyricVideo {...props} project={project}/>;};
const Root:React.FC=()=> <Composition id="LyricPoster" component={NormalizedVideo} durationInFrames={540} fps={30} width={1280} height={720} defaultProps={{project:demo,options:defaults,timeOffset:0,renderLength:18}} calculateMetadata={({props}:{props:VideoProps})=>({...renderSize(props.options),durationInFrames:Math.max(1,Math.round((props.renderLength??props.project.duration)*30))})}/>;
registerRoot(Root);
