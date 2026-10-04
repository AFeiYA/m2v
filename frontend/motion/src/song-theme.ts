export const SONG_THEMES={
 editorial:{name:'黑白编辑',background:'#101112',accent:'#e9ece5',motif:'none',palette:'monochrome',motion:.35},
 neon:{name:'霓虹舞台',background:'#100c19',accent:'#ff3988',motif:'rings',palette:'sakura',motion:.75},
 paper:{name:'暖纸海报',background:'#f7f0df',accent:'#a44725',motif:'none',palette:'amber',motion:.3},
} as const;
export type SongTheme='director'|keyof typeof SONG_THEMES;
