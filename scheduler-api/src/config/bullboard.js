import { createBullBoard } from '@bull-board/api';
import { BullMQAdapter } from '@bull-board/api/bullMQAdapter.js';
import { ExpressAdapter } from '@bull-board/express';
import { triggerQueue } from '../queue/trigger.queue.js';

// Create Bull Board UI adapter
const serverAdapter = new ExpressAdapter();
serverAdapter.setBasePath('/admin/queues');

// Create Bull Board instance with queue adapters
const { addQueue, removeQueue, setQueues, replaceQueues } = createBullBoard({
  queues: [
    new BullMQAdapter(triggerQueue),
  ],
  serverAdapter: serverAdapter,
});

export { serverAdapter, addQueue, removeQueue, setQueues, replaceQueues };
