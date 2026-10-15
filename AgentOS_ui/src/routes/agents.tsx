import { createFileRoute } from '@tanstack/react-router';
import { AgentGallery } from '@/components/agentos/agents';
export const Route = createFileRoute('/agents')({head:()=>({meta:[{title:'Deploy an agent · AgentOS'},{name:'description',content:'Explore purpose-built AI roles and deploy your next agent.'},{property:'og:title',content:'Deploy an agent · AgentOS'},{property:'og:description',content:'Explore purpose-built AI roles and deploy your next agent.'},{property:'og:type',content:'website'},{name:'twitter:card',content:'summary_large_image'}]}),component:AgentGallery});
