import type React from "react";
import type { Message } from "@langchain/langgraph-sdk";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Loader2, Copy, CopyCheck, Eye, EyeOff } from "lucide-react";
import { InputForm } from "@/components/InputForm";
import { Button } from "@/components/ui/button";
import { useState, ReactNode, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import {
  ActivityTimeline,
  ProcessedEvent,
} from "@/components/ActivityTimeline"; // Assuming ActivityTimeline is in the same dir or adjust path
import { ResearchThinkPanel } from "@/components/ResearchThinkPanel";
import { transformEventsToHierarchy, EventData } from "@/utils/dataTransformer";

// Markdown component props type from former ReportView
type MdComponentProps = {
  className?: string;
  children?: ReactNode;
  [key: string]: any; // 保留any类型以兼容ReactMarkdown
};

// Markdown components (from former ReportView.tsx)
const mdComponents = {
  h1: ({ className, children, ...props }: MdComponentProps) => (
    <h1 className={cn("text-2xl font-bold mt-4 mb-2", className)} {...props}>
      {children}
    </h1>
  ),
  h2: ({ className, children, ...props }: MdComponentProps) => (
    <h2 className={cn("text-xl font-bold mt-3 mb-2", className)} {...props}>
      {children}
    </h2>
  ),
  h3: ({ className, children, ...props }: MdComponentProps) => (
    <h3 className={cn("text-lg font-bold mt-3 mb-1", className)} {...props}>
      {children}
    </h3>
  ),
  p: ({ className, children, ...props }: MdComponentProps) => (
    <p className={cn("mb-3 leading-7", className)} {...props}>
      {children}
    </p>
  ),
  a: ({ className, children, href, ...props }: MdComponentProps) => (
    <Badge className="text-xs mx-0.5">
      <a
        className={cn("text-blue-400 hover:text-blue-300 text-xs", className)}
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        {...props}
      >
        {children}
      </a>
    </Badge>
  ),
  ul: ({ className, children, ...props }: MdComponentProps) => (
    <ul className={cn("list-disc pl-6 mb-3", className)} {...props}>
      {children}
    </ul>
  ),
  ol: ({ className, children, ...props }: MdComponentProps) => (
    <ol className={cn("list-decimal pl-6 mb-3", className)} {...props}>
      {children}
    </ol>
  ),
  li: ({ className, children, ...props }: MdComponentProps) => (
    <li className={cn("mb-1", className)} {...props}>
      {children}
    </li>
  ),
  blockquote: ({ className, children, ...props }: MdComponentProps) => (
    <blockquote
      className={cn(
        "border-l-4 border-neutral-600 pl-4 italic my-3 text-sm",
        className
      )}
      {...props}
    >
      {children}
    </blockquote>
  ),
  code: ({ className, children, ...props }: MdComponentProps) => (
    <code
      className={cn(
        "bg-neutral-900 rounded px-1 py-0.5 font-mono text-xs",
        className
      )}
      {...props}
    >
      {children}
    </code>
  ),
  pre: ({ className, children, ...props }: MdComponentProps) => (
    <pre
      className={cn(
        "bg-neutral-900 p-3 rounded-lg overflow-x-auto font-mono text-xs my-3",
        className
      )}
      {...props}
    >
      {children}
    </pre>
  ),
  hr: ({ className, ...props }: MdComponentProps) => (
    <hr className={cn("border-neutral-600 my-4", className)} {...props} />
  ),
  table: ({ className, children, ...props }: MdComponentProps) => (
    <div className="my-3 overflow-x-auto">
      <table className={cn("border-collapse w-full", className)} {...props}>
        {children}
      </table>
    </div>
  ),
  th: ({ className, children, ...props }: MdComponentProps) => (
    <th
      className={cn(
        "border border-neutral-600 px-3 py-2 text-left font-bold",
        className
      )}
      {...props}
    >
      {children}
    </th>
  ),
  td: ({ className, children, ...props }: MdComponentProps) => (
    <td
      className={cn("border border-neutral-600 px-3 py-2", className)}
      {...props}
    >
      {children}
    </td>
  ),
};

// Props for HumanMessageBubble
interface HumanMessageBubbleProps {
  message: Message;
  mdComponents: typeof mdComponents;
}

// HumanMessageBubble Component
const HumanMessageBubble: React.FC<HumanMessageBubbleProps> = ({
  message,
  mdComponents,
}) => {
  return (
    <div
      className={`text-white rounded-3xl break-words min-h-7 bg-neutral-700 max-w-[100%] sm:max-w-[90%] px-4 pt-3 rounded-br-lg`}
    >
      <ReactMarkdown components={mdComponents}>
        {typeof message.content === "string"
          ? message.content
          : JSON.stringify(message.content)}
      </ReactMarkdown>
    </div>
  );
};

// Props for AiMessageBubble
interface AiMessageBubbleProps {
  message: Message;
  historicalActivity: ProcessedEvent[] | undefined;
  liveActivity: ProcessedEvent[] | undefined;
  isLastMessage: boolean;
  isOverallLoading: boolean;
  mdComponents: typeof mdComponents;
  handleCopy: (text: string, messageId: string) => void;
  copiedMessageId: string | null;
  showCompactTimeline: boolean;
}

// AiMessageBubble Component
const AiMessageBubble: React.FC<AiMessageBubbleProps> = ({
  message,
  historicalActivity,
  liveActivity,
  isLastMessage,
  isOverallLoading,
  mdComponents,
  handleCopy,
  copiedMessageId,
  showCompactTimeline,
}) => {
  // 🔧 IMPROVED: 改进活动显示逻辑 - 优先显示快照
  // 1. 如果有历史活动快照，优先显示快照（避免闪现）
  // 2. 只有最后一条消息且没有快照时，才显示实时活动
  const hasHistoricalActivity = historicalActivity && historicalActivity.length > 0;
  const shouldShowLiveActivity = isLastMessage && isOverallLoading && !hasHistoricalActivity;
  
  const activityForThisBubble = hasHistoricalActivity 
    ? historicalActivity 
    : (shouldShowLiveActivity ? liveActivity : []);
  const isLiveActivityForThisBubble = shouldShowLiveActivity;

  // 🔧 DEBUG: 简化调试信息
  if (process.env.NODE_ENV === 'development') {
    console.log(`🎯 AiMessageBubble [${message.id?.slice(-8)}]:`, {
      isLastMessage,
      hasHistoricalActivity,
      shouldShowLiveActivity,
      activityCount: activityForThisBubble?.length || 0,
      showingType: hasHistoricalActivity ? 'snapshot' : (shouldShowLiveActivity ? 'live' : 'none')
    });
  }

  return (
    <div className={`relative break-words flex flex-col`}>
      {/* 🔧 DEBUG: 添加状态显示信息 */}
      {process.env.NODE_ENV === 'development' && (
        <div className="text-xs bg-blue-900 p-1 mb-2 rounded text-white">
          Message: {message.id} | Historical: {historicalActivity?.length || 0} | Live: {liveActivity?.length || 0} | Showing: {activityForThisBubble?.length || 0}
        </div>
      )}
      {/* 只在没有思考面板时显示活动时间线 */}
      {!showCompactTimeline && activityForThisBubble && activityForThisBubble.length > 0 && (
        <div className="mb-3 border-b border-neutral-700 pb-3 text-xs">
          <ActivityTimeline
            processedEvents={activityForThisBubble}
            isLoading={isLiveActivityForThisBubble}
          />
        </div>
      )}
      <ReactMarkdown components={mdComponents}>
        {typeof message.content === "string"
          ? message.content
          : JSON.stringify(message.content)}
      </ReactMarkdown>
      <Button
        variant="default"
        className="cursor-pointer bg-neutral-700 border-neutral-600 text-neutral-300 self-end"
        onClick={() =>
          handleCopy(
            typeof message.content === "string"
              ? message.content
              : JSON.stringify(message.content),
            message.id!
          )
        }
      >
        {copiedMessageId === message.id ? "Copied" : "Copy"}
        {copiedMessageId === message.id ? <CopyCheck /> : <Copy />}
      </Button>
    </div>
  );
};

interface ChatMessagesViewProps {
  messages: Message[];
  isLoading: boolean;
  scrollAreaRef: React.RefObject<HTMLDivElement | null>;
  onSubmit: (inputValue: string, effort: string, model: string) => void;
  onCancel: () => void;
  liveActivityEvents: ProcessedEvent[];
  historicalActivities: Record<string, ProcessedEvent[]>;
}

export function ChatMessagesView({
  messages,
  isLoading,
  scrollAreaRef,
  onSubmit,
  onCancel,
  liveActivityEvents,
  historicalActivities,
}: ChatMessagesViewProps) {
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [showThinkPanel, setShowThinkPanel] = useState(true);

  const handleCopy = async (text: string, messageId: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedMessageId(messageId);
      setTimeout(() => setCopiedMessageId(null), 2000); // Reset after 2 seconds
    } catch (err) {
      console.error("Failed to copy text: ", err);
    }
  };

  // 获取转换后的研究数据
  const researchData = useMemo(() => {
    try {
      // 从sessionStorage获取事件数据
      const storedEvents = JSON.parse(sessionStorage.getItem('research_events') || '[]') as EventData[];
      if (storedEvents.length === 0) {
        console.log("🔍 Think Panel: 没有存储的事件数据");
        return null;
      }
      
      console.log(`🔍 Think Panel: 处理 ${storedEvents.length} 个事件`);
      const result = transformEventsToHierarchy(storedEvents, messages || []);
      console.log("🔍 Think Panel: 转换结果", {
        tasksCount: result.tasks.length,
        overallStatus: result.overallStatus,
        currentTaskId: result.currentTaskId,
        tasks: result.tasks.map(t => ({
          id: t.taskId,
          description: t.description,
          stepsCount: t.steps.length,
          steps: t.steps.map(s => ({ type: s.type, title: s.title, status: s.status }))
        }))
      });
      
      return result;
    } catch (error) {
      console.warn("⚠️ Think Panel: 无法获取研究数据:", error);
      return null;
    }
  }, [messages, liveActivityEvents, isLoading]); // 添加isLoading依赖确保实时更新

  return (
    <div className="flex h-full">
      {/* 左侧消息区域 */}
      <div className={`flex flex-col transition-all duration-300 ${showThinkPanel ? 'w-1/2' : 'w-full'}`}>
        {/* 切换按钮 */}
        <div className="flex justify-between items-center p-4 border-b border-neutral-800 flex-shrink-0">
          <h3 className="text-lg font-medium text-white">Conversation</h3>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowThinkPanel(!showThinkPanel)}
            className="text-neutral-400 border-neutral-600 hover:bg-neutral-700"
          >
            {showThinkPanel ? <EyeOff className="h-4 w-4 mr-2" /> : <Eye className="h-4 w-4 mr-2" />}
            {showThinkPanel ? 'Hide Think Panel' : 'Show Think Panel'}
          </Button>
        </div>

        <ScrollArea className="flex-grow h-0" ref={scrollAreaRef}>
          <div className="p-4 md:p-6 space-y-2 min-h-full">
            {messages.map((message, index) => {
              const isLast = index === messages.length - 1;
              return (
                <div key={message.id || `msg-${index}`} className="space-y-3">
                  <div
                    className={`flex items-start gap-3 ${
                      message.type === "human" ? "justify-end" : ""
                    }`}
                  >
                    {message.type === "human" ? (
                      <HumanMessageBubble
                        message={message}
                        mdComponents={mdComponents}
                      />
                    ) : (
                      <AiMessageBubble
                        message={message}
                        historicalActivity={historicalActivities[message.id!]}
                        liveActivity={liveActivityEvents}
                        isLastMessage={isLast}
                        isOverallLoading={isLoading}
                        mdComponents={mdComponents}
                        handleCopy={handleCopy}
                        copiedMessageId={copiedMessageId}
                        showCompactTimeline={showThinkPanel}
                      />
                    )}
                  </div>
                </div>
              );
            })}
            {/* 🔧 FIXED: 改进loading状态显示 - 只在真正需要时显示 */}
            {isLoading && messages.length === 0 && (
              <div className="flex items-start gap-3 mt-3">
                <div className="relative group max-w-[85%] md:max-w-[80%] rounded-xl p-3 shadow-sm break-words bg-neutral-800 text-neutral-100 rounded-bl-none w-full min-h-[56px]">
                  <div className="flex items-center justify-start h-full">
                    <Loader2 className="h-5 w-5 animate-spin text-neutral-400 mr-2" />
                    <span>Initializing research...</span>
                  </div>
                </div>
              </div>
            )}
            {/* 🔧 NEW: 当最后一条是human消息且正在loading时，显示处理状态 */}
            {isLoading && messages.length > 0 && messages[messages.length - 1].type === "human" && (
              <div className="flex items-start gap-3 mt-3">
                <div className="relative group max-w-[85%] md:max-w-[80%] rounded-xl p-3 shadow-sm break-words bg-neutral-800 text-neutral-100 rounded-bl-none w-full min-h-[56px]">
                  {showThinkPanel ? (
                    <div className="flex items-center justify-start h-full">
                      <Loader2 className="h-5 w-5 animate-spin text-neutral-400 mr-2" />
                      <span>Processing... (Detailed information can be found in the right think panel)</span>
                    </div>
                  ) : (
                    liveActivityEvents.length > 0 ? (
                      <div className="text-xs">
                        <ActivityTimeline
                          processedEvents={liveActivityEvents}
                          isLoading={true}
                        />
                      </div>
                    ) : (
                      <div className="flex items-center justify-start h-full">
                        <Loader2 className="h-5 w-5 animate-spin text-neutral-400 mr-2" />
                        <span>Processing...</span>
                      </div>
                    )
                  )}
                </div>
              </div>
            )}
          </div>
        </ScrollArea>
        
        <div className="flex-shrink-0">
          <InputForm
            onSubmit={onSubmit}
            isLoading={isLoading}
            onCancel={onCancel}
            hasHistory={messages.length > 0}
          />
        </div>
      </div>

      {/* 右侧思考面板 - 固定高度，独立滚动 */}
      {showThinkPanel && (
        <div className="w-1/2 border-l border-neutral-800 flex flex-col h-full">
          <ResearchThinkPanel 
            researchData={researchData}
            isLoading={isLoading}
          />
        </div>
      )}
    </div>
  );
}
