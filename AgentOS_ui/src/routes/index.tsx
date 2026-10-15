import { createFileRoute } from '@tanstack/react-router';
import { Dashboard } from '@/components/agentos/dashboard';
export const Route = createFileRoute('/')({head:()=>({meta:[{title:'Dashboard · AgentOS'},{name:'description',content:'Your AI agent workforce at a glance. Monitor agents, spending, runs, and activity.'},{property:'og:title',content:'Your agent workforce · AgentOS'},{property:'og:description',content:'One workspace for your entire AI agent workforce.'},{property:'og:type',content:'website'},{name:'twitter:card',content:'summary_large_image'}]}),component:Dashboard});
