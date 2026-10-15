import { createFileRoute } from '@tanstack/react-router';
import { Billing } from '@/components/agentos/billing';
export const Route = createFileRoute('/billing')({head:()=>({meta:[{title:'Spend & settlement · AgentOS'},{name:'description',content:'Track real-time agent spending, budgets, and rated usage.'},{property:'og:title',content:'Spend & settlement · AgentOS'},{property:'og:description',content:'Track real-time agent spending, budgets, and rated usage.'},{property:'og:type',content:'website'},{name:'twitter:card',content:'summary_large_image'}]}),component:Billing});
