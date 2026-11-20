<template>
  <section class="page" data-module="quality">
    <header class="page-head">
      <div>
        <h2>数据质量校验</h2>
        <p class="page-desc">
          对标准化事件做字段级校验：批次冻结规则口径，同事件同规则只保留一条当前结论，
          阻断异常写入采集日志，处置依据全程留痕、可沿用可撤销。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openEventModal">登记标准化事件</button>
        <button class="btn primary" type="button" @click="openRuleModal">登记校验规则</button>
        <button class="btn" type="button" @click="reload">刷新数据</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <nav class="qc-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        class="qc-tab"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </nav>

    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>
    <p v-if="infoMessage" class="info-text">{{ infoMessage }}</p>

    <!-- 回查台账 -->
    <div v-if="activeTab === 'trace'" class="qc-panel">
      <form class="filter-bar" @submit.prevent="runTrace">
        <label class="filter-item">
          <span>事件</span>
          <select v-model.number="traceEventId">
            <option v-for="ev in events" :key="ev.id" :value="ev.id">{{ ev.事件编号 }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>规则</span>
          <select v-model.number="traceRuleId">
            <option v-for="rule in rules" :key="rule.id" :value="rule.id">{{ rule.规则编号 }}（{{ rule.校验字段 }}）</option>
          </select>
        </label>
        <button class="btn primary" type="submit">回查警报与处置</button>
      </form>

      <template v-if="trace">
        <div class="trace-grid">
          <article class="stat-card">
            <span class="stat-label">警报是否仍有效</span>
            <strong class="stat-value" :class="trace.警报是否仍有效 ? 'badge block' : 'badge pass'">
              {{ trace.警报是否仍有效 ? '仍有效' : '已失效' }}
            </strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">当轮实际使用容差</span>
            <strong class="stat-value">{{ trace.当轮实际使用容差 ?? '—' }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">当轮采用版本</span>
            <strong class="stat-value">V{{ trace.当轮采用版本号 ?? '—' }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">已派出处置</span>
            <strong class="stat-value">{{ trace.处置去向.length }} 单</strong>
          </article>
        </div>

        <h4>当前有效结论</h4>
        <table v-if="trace.当前有效结论" class="data-table">
          <thead>
            <tr><th>字段</th><th>结论</th><th>实测值</th><th>偏差</th><th>口径（期望值/容差）</th><th>版本</th><th>判定说明</th></tr>
          </thead>
          <tbody>
            <tr>
              <td>{{ trace.当前有效结论.校验字段 }}</td>
              <td><span class="badge" :class="trace.当前有效结论.结论 === '通过' ? 'pass' : 'fail'">{{ trace.当前有效结论.结论 }}</span></td>
              <td>{{ trace.当前有效结论.实测值 ?? '—' }}</td>
              <td>{{ trace.当前有效结论.偏差量 ?? '—' }}</td>
              <td>{{ trace.当前有效结论.采用口径.期望值 }} / {{ trace.当前有效结论.采用口径.容差 }}</td>
              <td>V{{ trace.当前有效结论.采用版本号 }}</td>
              <td>{{ trace.当前有效结论.判定说明 }}</td>
            </tr>
          </tbody>
        </table>

        <h4>结论沿革（同一事件+规则的全部历史结论）</h4>
        <table class="data-table">
          <thead>
            <tr><th>结论id</th><th>批次id</th><th>结论</th><th>版本</th><th>容差</th><th>结论状态</th><th>校验时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in trace.结论沿革" :key="row.id">
              <td>{{ row.id }}</td>
              <td>{{ row.批次id }}</td>
              <td><span class="badge" :class="row.结论 === '通过' ? 'pass' : 'fail'">{{ row.结论 }}</span></td>
              <td>V{{ row.采用版本号 }}</td>
              <td>{{ row.采用口径.容差 }}</td>
              <td>{{ row.结论状态 }}</td>
              <td>{{ row.校验时间 }}</td>
            </tr>
          </tbody>
        </table>

        <h4>处置去向与凭据链</h4>
        <table class="data-table">
          <thead>
            <tr><th>处置单号</th><th>处理人</th><th>动作</th><th>状态</th><th>依据版本</th><th>依据容差</th><th>凭据链</th></tr>
          </thead>
          <tbody>
            <tr v-for="dsp in trace.处置去向" :key="dsp.id">
              <td>{{ dsp.处置单号 }}</td>
              <td>{{ dsp.处理人 }}</td>
              <td>{{ dsp.处置动作 }}</td>
              <td><span class="badge" :class="dsp.处置状态 === '已撤销' ? 'muted' : 'block'">{{ dsp.处置状态 }}</span></td>
              <td>V{{ dsp.依据版本号 }}</td>
              <td>{{ dsp.依据口径快照.容差 }}</td>
              <td>
                <ul class="chain-list">
                  <li v-for="(link, idx) in dsp.凭据链" :key="idx">
                    {{ link.时间 }} · {{ link.动作 }} · {{ link.处理人 }}
                    <template v-if="link.说明"> · {{ link.说明 }}</template>
                  </li>
                </ul>
              </td>
            </tr>
            <tr v-if="!trace.处置去向.length"><td colspan="7" class="empty-state">暂无处置记录</td></tr>
          </tbody>
        </table>
      </template>
      <p v-else class="empty-state">请选择事件与规则后发起回查</p>
    </div>

    <!-- 标准化事件 -->
    <div v-if="activeTab === 'events'" class="qc-panel">
      <table class="data-table">
        <thead>
          <tr><th>id</th><th>事件编号</th><th>事件类型</th><th>来源批次</th><th>标准化字段</th><th>原始载荷</th></tr>
        </thead>
        <tbody>
          <tr v-for="ev in events" :key="ev.id">
            <td>{{ ev.id }}</td>
            <td>{{ ev.事件编号 }}</td>
            <td>{{ ev.事件类型 }}</td>
            <td>{{ ev.来源批次 || '—' }}</td>
            <td>
              <span v-for="(value, key) in ev.标准化字段" :key="key" class="field-chip">{{ key }}={{ value }}</span>
            </td>
            <td>{{ ev.事件载荷 }}</td>
          </tr>
          <tr v-if="!events.length"><td colspan="6" class="empty-state">暂无标准化事件</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 规则与版本 -->
    <div v-if="activeTab === 'rules'" class="qc-panel">
      <table class="data-table">
        <thead>
          <tr><th>规则编号</th><th>校验字段</th><th>校验类型</th><th>当前版本</th><th>期望值</th><th>容差</th><th>阻断级别</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="rule in rules" :key="rule.id">
            <td>{{ rule.规则编号 }}</td>
            <td>{{ rule.校验字段 }}</td>
            <td>{{ rule.校验类型 }}</td>
            <td>V{{ rule.当前版本号 }}</td>
            <td>{{ latestRevision(rule.id)?.期望值 ?? '—' }}</td>
            <td>{{ latestRevision(rule.id)?.容差 ?? '—' }}</td>
            <td><span class="badge" :class="latestRevision(rule.id)?.阻断级别 === '阻断' ? 'block' : 'muted'">{{ latestRevision(rule.id)?.阻断级别 }}</span></td>
            <td class="row-actions">
              <button class="link" type="button" @click="toggleRevisions(rule.id)">
                {{ expandedRule === rule.id ? '收起版本' : '查看版本' }}
              </button>
              <button class="link" type="button" @click="openCorrectModal(rule)">更正容差</button>
            </td>
          </tr>
        </tbody>
      </table>

      <template v-if="expandedRule !== null">
        <h4>规则版本沿革（更正只追加新版本，历史口径永不覆盖）</h4>
        <table class="data-table">
          <thead>
            <tr><th>版本</th><th>期望值</th><th>容差</th><th>阻断级别</th><th>口径说明</th><th>变更原因</th><th>生效时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="rev in revisionMap[expandedRule] || []" :key="rev.id">
              <td>V{{ rev.版本号 }}</td>
              <td>{{ rev.期望值 }}</td>
              <td>{{ rev.容差 }}</td>
              <td>{{ rev.阻断级别 }}</td>
              <td>{{ rev.口径说明 || '—' }}</td>
              <td>{{ rev.变更原因 }}</td>
              <td>{{ rev.生效时间 }}</td>
            </tr>
          </tbody>
        </table>
      </template>
    </div>

    <!-- 批次与结论 -->
    <div v-if="activeTab === 'batches'" class="qc-panel">
      <div class="page-actions" style="margin-bottom: 10px">
        <button class="btn primary" type="button" @click="runCheck(null)">对全部事件发起校验</button>
      </div>
      <h4>校验批次（每批冻结独立规则快照）</h4>
      <table class="data-table">
        <thead>
          <tr><th>批次编号</th><th>触发说明</th><th>状态</th><th>结论数</th><th>阻断异常</th><th>冻结时间</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="batch in batches" :key="batch.id">
            <td>{{ batch.批次编号 }}</td>
            <td>{{ batch.触发说明 }}</td>
            <td>{{ batch.状态 }}</td>
            <td>{{ batch.结论数 }}</td>
            <td><span class="badge" :class="batch.阻断异常数 ? 'block' : 'pass'">{{ batch.阻断异常数 }}</span></td>
            <td>{{ batch.冻结时间 }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="toggleResults(batch.id)">
                {{ expandedBatch === batch.id ? '收起结论' : '查看结论' }}
              </button>
              <button class="link" type="button" @click="recheck(batch.id)">容差更正后复核重算</button>
            </td>
          </tr>
        </tbody>
      </table>

      <template v-if="expandedBatch !== null">
        <h4>字段校验结论（同事件+规则仅一条当前有效）</h4>
        <table class="data-table">
          <thead>
            <tr><th>事件</th><th>规则</th><th>失败字段</th><th>结论</th><th>阻断</th><th>版本/容差</th><th>结论状态</th><th>判定说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in resultsByBatch[expandedBatch] || []" :key="row.id">
              <td>{{ row.事件编号 }}</td>
              <td>{{ row.规则编号 }}</td>
              <td>{{ row.失败字段 || '—' }}</td>
              <td><span class="badge" :class="row.结论 === '通过' ? 'pass' : 'fail'">{{ row.结论 }}</span></td>
              <td><span class="badge" :class="row.是否阻断 ? 'block' : 'muted'">{{ row.是否阻断 ? '阻断' : '不阻断' }}</span></td>
              <td>V{{ row.采用版本号 }} / 容差{{ row.采用口径.容差 }}</td>
              <td>{{ row.结论状态 }}</td>
              <td>{{ row.判定说明 }}</td>
            </tr>
          </tbody>
        </table>
      </template>
    </div>

    <!-- 异常与处置 -->
    <div v-if="activeTab === 'anomalies'" class="qc-panel">
      <table class="data-table">
        <thead>
          <tr><th>异常编号</th><th>事件</th><th>规则/字段</th><th>首报版本</th><th>重算次数</th><th>异常状态</th><th>处置操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="anm in anomalies" :key="anm.id">
            <td>{{ anm.异常编号 }}</td>
            <td>{{ anm.事件编号 }}</td>
            <td>{{ anm.规则编号 }} / {{ anm.校验字段 }}</td>
            <td>V{{ anm.首报版本号 }}（容差{{ anm.首报口径快照.容差 }}）</td>
            <td>{{ anm.重算次数 }}</td>
            <td><span class="badge" :class="anm.异常状态 === '重算通过已解除' || anm.异常状态 === '已撤销处置' ? 'pass' : 'block'">{{ anm.异常状态 }}</span></td>
            <td class="row-actions">
              <button
                v-if="anm.是否阻断 && anm.异常状态 !== '重算通过已解除' && anm.异常状态 !== '已撤销处置'"
                class="link" type="button" @click="openDispositionModal(anm)"
              >派出处置</button>
              <button class="link" type="button" @click="expandedAnomaly = expandedAnomaly === anm.id ? null : anm.id">
                {{ expandedAnomaly === anm.id ? '收起凭据' : '处置凭据' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <template v-if="expandedAnomaly !== null">
        <h4>处置记录与冲突凭据（落库后只能沿用/撤销，不能改写）</h4>
        <table class="data-table">
          <thead>
            <tr><th>处置单号</th><th>处理人</th><th>动作</th><th>状态</th><th>依据版本/容差</th><th>凭据链</th><th>结论冲突处理</th></tr>
          </thead>
          <tbody>
            <tr v-for="dsp in dispositionsByAnomaly[expandedAnomaly] || []" :key="dsp.id">
              <td>{{ dsp.处置单号 }}</td>
              <td>{{ dsp.处理人 }}</td>
              <td>{{ dsp.处置动作 }}</td>
              <td><span class="badge" :class="dsp.处置状态 === '已撤销' ? 'muted' : 'block'">{{ dsp.处置状态 }}</span></td>
              <td>V{{ dsp.依据版本号 }} / 容差{{ dsp.依据口径快照.容差 }}</td>
              <td>
                <ul class="chain-list">
                  <li v-for="(link, idx) in dsp.凭据链" :key="idx">
                    {{ link.时间 }} · {{ link.动作 }} · {{ link.处理人 }}
                    <template v-if="link.当前结论"> · 当前结论：{{ link.当前结论 }}（V{{ link.当前版本号 }}）</template>
                  </li>
                </ul>
              </td>
              <td class="row-actions">
                <button v-if="dsp.处置状态 !== '已撤销' && dsp.处置状态 !== '复核沿用'" class="link" type="button" @click="resolveConflict(dsp, '复核沿用')">复核沿用</button>
                <button v-if="dsp.处置状态 !== '已撤销'" class="link" type="button" @click="resolveConflict(dsp, '已撤销')">撤销处置</button>
              </td>
            </tr>
            <tr v-if="!(dispositionsByAnomaly[expandedAnomaly] || []).length"><td colspan="7" class="empty-state">该异常暂无处置记录</td></tr>
          </tbody>
        </table>
      </template>
    </div>

    <!-- 登记事件弹窗 -->
    <Teleport to="body">
      <div v-if="showEventModal" class="modal-overlay" @click.self="showEventModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>登记标准化事件</h3>
            <button class="btn ghost" type="button" @click="showEventModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitEvent">
            <label class="modal-field"><span>事件编号</span><input v-model="eventForm.事件编号" required /></label>
            <label class="modal-field"><span>事件类型</span><input v-model="eventForm.事件类型" placeholder="传感器读数" /></label>
            <label class="modal-field"><span>来源批次</span><input v-model="eventForm.来源批次" /></label>
            <label class="modal-field">
              <span>事件载荷（字段=值，逗号分隔，如：水温偏差=2.4,设备编号=SENS-A17）</span>
              <input v-model="eventForm.事件载荷" required />
            </label>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showEventModal = false">取消</button>
              <button class="btn primary" type="submit">提交登记</button>
            </footer>
          </form>
        </div>
      </div>
    </Teleport>

    <!-- 登记规则弹窗 -->
    <Teleport to="body">
      <div v-if="showRuleModal" class="modal-overlay" @click.self="showRuleModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>登记校验规则</h3>
            <button class="btn ghost" type="button" @click="showRuleModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitRule">
            <label class="modal-field"><span>规则编号</span><input v-model="ruleForm.规则编号" required /></label>
            <label class="modal-field"><span>校验字段</span><input v-model="ruleForm.校验字段" required /></label>
            <label class="modal-field">
              <span>校验类型</span>
              <select v-model="ruleForm.校验类型">
                <option v-for="t in checkTypes" :key="t" :value="t">{{ t }}</option>
              </select>
            </label>
            <label v-if="ruleForm.校验类型 === '数值偏差'" class="modal-field"><span>期望值</span><input v-model="ruleForm.期望值" required /></label>
            <label v-if="ruleForm.校验类型 === '数值偏差'" class="modal-field"><span>容差</span><input v-model="ruleForm.容差" required /></label>
            <label v-if="ruleForm.校验类型 === '枚举取值'" class="modal-field"><span>允许枚举（| 分隔）</span><input v-model="ruleForm.允许枚举" placeholder="一车间|二车间" /></label>
            <label class="modal-field">
              <span>阻断级别</span>
              <select v-model="ruleForm.阻断级别"><option value="阻断">阻断</option><option value="提醒">提醒</option></select>
            </label>
            <label class="modal-field"><span>口径说明</span><input v-model="ruleForm.口径说明" /></label>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showRuleModal = false">取消</button>
              <button class="btn primary" type="submit">提交登记</button>
            </footer>
          </form>
        </div>
      </div>
    </Teleport>

    <!-- 容差更正弹窗 -->
    <Teleport to="body">
      <div v-if="showCorrectModal" class="modal-overlay" @click.self="showCorrectModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>容差/口径更正（追加新版本）</h3>
            <button class="btn ghost" type="button" @click="showCorrectModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitCorrect">
            <p class="page-desc">规则：{{ correctForm.规则编号 }} · 当前 V{{ correctForm.当前版本号 }}。留空字段沿用当前版本。</p>
            <label v-if="correctForm.校验类型 === '数值偏差'" class="modal-field"><span>新期望值</span><input v-model="correctForm.期望值" /></label>
            <label v-if="correctForm.校验类型 === '数值偏差'" class="modal-field"><span>新容差</span><input v-model="correctForm.容差" /></label>
            <label class="modal-field">
              <span>阻断级别</span>
              <select v-model="correctForm.阻断级别"><option value="阻断">阻断</option><option value="提醒">提醒</option></select>
            </label>
            <label class="modal-field"><span>更正原因</span><input v-model="correctForm.更正原因" required /></label>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showCorrectModal = false">取消</button>
              <button class="btn primary" type="submit">生成新版本</button>
            </footer>
          </form>
        </div>
      </div>
    </Teleport>

    <!-- 派出处置弹窗 -->
    <Teleport to="body">
      <div v-if="showDispositionModal" class="modal-overlay" @click.self="showDispositionModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>派出阻断处置</h3>
            <button class="btn ghost" type="button" @click="showDispositionModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitDisposition">
            <p class="page-desc">异常 {{ dispositionForm.异常编号 }}：处置将固化首报口径（V{{ dispositionForm.首报版本号 }}），后续重算不会改写本单据。</p>
            <label class="modal-field"><span>处理人</span><input v-model="dispositionForm.处理人" required /></label>
            <label class="modal-field"><span>处置动作</span><input v-model="dispositionForm.处置动作" placeholder="派发现场检修工单" required /></label>
            <label class="modal-field"><span>处置说明</span><input v-model="dispositionForm.处置说明" /></label>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showDispositionModal = false">取消</button>
              <button class="btn primary" type="submit">派出并固化依据</button>
            </footer>
          </form>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

const ENDPOINT = '/api/quality'
const checkTypes = ['数值偏差', '枚举取值', '必填非空']
const tabs = [
  { key: 'trace', label: '回查台账' },
  { key: 'events', label: '标准化事件' },
  { key: 'rules', label: '校验规则与版本' },
  { key: 'batches', label: '校验批次与结论' },
  { key: 'anomalies', label: '阻断异常与处置' },
] as const

type Row = Record<string, any>
const activeTab = ref<(typeof tabs)[number]['key']>('trace')
const events = ref<Row[]>([])
const rules = ref<Row[]>([])
const batches = ref<Row[]>([])
const results = ref<Row[]>([])
const anomalies = ref<Row[]>([])
const dispositions = ref<Row[]>([])
const revisionMap = reactive<Record<number, Row[]>>({})
const errorMessage = ref('')
const infoMessage = ref('')

const expandedRule = ref<number | null>(null)
const expandedBatch = ref<number | null>(null)
const expandedAnomaly = ref<number | null>(null)

const traceEventId = ref<number | null>(null)
const traceRuleId = ref<number | null>(null)
const trace = ref<Row | null>(null)

const showEventModal = ref(false)
const showRuleModal = ref(false)
const showCorrectModal = ref(false)
const showDispositionModal = ref(false)
const eventForm = reactive<Record<string, string>>({ 事件编号: '', 事件类型: '传感器读数', 来源批次: '', 事件载荷: '' })
const ruleForm = reactive<Record<string, string>>({ 规则编号: '', 校验字段: '', 校验类型: '数值偏差', 期望值: '', 容差: '', 允许枚举: '', 阻断级别: '阻断', 口径说明: '' })
const correctForm = reactive<Row>({ 规则id: null, 规则编号: '', 校验类型: '数值偏差', 当前版本号: 1, 期望值: '', 容差: '', 阻断级别: '阻断', 更正原因: '' })
const dispositionForm = reactive<Row>({ 异常id: null, 异常编号: '', 首报版本号: 1, 处理人: '', 处置动作: '', 处置说明: '' })

const stats = computed(() => [
  { label: '标准化事件', value: events.value.length },
  { label: '校验批次', value: batches.value.length },
  { label: '阻断异常（未解除）', value: anomalies.value.filter((a) => !['重算通过已解除', '已撤销处置'].includes(a.异常状态)).length },
  { label: '已派出处置', value: dispositions.value.length },
])

const resultsByBatch = computed(() => {
  const map: Record<number, Row[]> = {}
  for (const row of results.value) {
    (map[row.批次id] ||= []).push(row)
  }
  return map
})

const dispositionsByAnomaly = computed(() => {
  const map: Record<number, Row[]> = {}
  for (const row of dispositions.value) {
    (map[row.异常id] ||= []).push(row)
  }
  return map
})

function latestRevision(ruleId: number): Row | undefined {
  const list = revisionMap[ruleId]
  return list ? list[list.length - 1] : undefined
}

async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(`${ENDPOINT}${path}`, init)
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(data.message || `接口返回 ${response.status}`)
  }
  return response.json()
}

function flash(message: string, ok = true) {
  if (ok) {
    infoMessage.value = message
    errorMessage.value = ''
  } else {
    errorMessage.value = message
    infoMessage.value = ''
  }
}

async function reload() {
  try {
    const [ev, rl, bt, rs, an, dp] = await Promise.all([
      api<{ items: Row[] }>('/events'),
      api<{ items: Row[] }>('/rules'),
      api<{ items: Row[] }>('/batches'),
      api<{ items: Row[] }>('/results'),
      api<{ items: Row[] }>('/anomalies'),
      api<{ items: Row[] }>('/dispositions'),
    ])
    events.value = ev.items
    rules.value = rl.items
    batches.value = bt.items
    results.value = rs.items
    anomalies.value = an.items
    dispositions.value = dp.items
    if (traceEventId.value === null && events.value.length) traceEventId.value = events.value[0].id
    if (traceRuleId.value === null && rules.value.length) traceRuleId.value = rules.value[0].id
    await Promise.all(rules.value.map((rule) => loadRevisions(rule.id)))
  } catch (error) {
    flash(error instanceof Error ? error.message : '数据质量校验数据加载失败', false)
  }
}

async function loadRevisions(ruleId: number) {
  const data = await api<{ items: Row[] }>(`/rules/${ruleId}/revisions`)
  revisionMap[ruleId] = data.items
}

async function toggleRevisions(ruleId: number) {
  expandedRule.value = expandedRule.value === ruleId ? null : ruleId
  if (expandedRule.value !== null && !revisionMap[ruleId]) {
    await loadRevisions(ruleId)
  }
}

async function toggleResults(batchId: number) {
  expandedBatch.value = expandedBatch.value === batchId ? null : batchId
}

function openEventModal() {
  Object.assign(eventForm, { 事件编号: '', 事件类型: '传感器读数', 来源批次: '', 事件载荷: '' })
  showEventModal.value = true
}

async function submitEvent() {
  try {
    const data = await api<{ message: string }>('/events', {
      method: 'POST',
      body: JSON.stringify({ values: { ...eventForm } }),
    })
    showEventModal.value = false
    await reload()
    flash(data.message || '标准化事件已登记')
  } catch (error) {
    flash(error instanceof Error ? error.message : '事件登记失败', false)
  }
}

function openRuleModal() {
  Object.assign(ruleForm, { 规则编号: '', 校验字段: '', 校验类型: '数值偏差', 期望值: '', 容差: '', 允许枚举: '', 阻断级别: '阻断', 口径说明: '' })
  showRuleModal.value = true
}

async function submitRule() {
  try {
    const data = await api<{ message: string }>('/rules', {
      method: 'POST',
      body: JSON.stringify({ values: { ...ruleForm } }),
    })
    showRuleModal.value = false
    await reload()
    flash(data.message || '校验规则已登记')
  } catch (error) {
    flash(error instanceof Error ? error.message : '规则登记失败', false)
  }
}

function openCorrectModal(rule: Row) {
  Object.assign(correctForm, {
    规则id: rule.id,
    规则编号: rule.规则编号,
    校验类型: rule.校验类型,
    当前版本号: rule.当前版本号,
    期望值: '',
    容差: '',
    阻断级别: latestRevision(rule.id)?.阻断级别 || '阻断',
    更正原因: '',
  })
  showCorrectModal.value = true
}

async function submitCorrect() {
  try {
    const values: Record<string, string> = {
      阻断级别: correctForm.阻断级别,
      更正原因: correctForm.更正原因,
    }
    if (correctForm.期望值) values.期望值 = correctForm.期望值
    if (correctForm.容差) values.容差 = correctForm.容差
    const data = await api<{ message: string }>(`/rules/${correctForm.规则id}/revisions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    showCorrectModal.value = false
    await reload()
    flash(data.message || '新口径版本已生成')
  } catch (error) {
    flash(error instanceof Error ? error.message : '容差更正失败', false)
  }
}

async function runCheck(eventIds: number[] | null) {
  try {
    const values: Record<string, unknown> = { 触发说明: '人工发起数据质量校验' }
    if (eventIds) values.event_ids = eventIds
    const data = await api<{ message: string }>('/checks', {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    await reload()
    flash(data.message)
  } catch (error) {
    flash(error instanceof Error ? error.message : '校验执行失败', false)
  }
}

async function recheck(batchId: number) {
  try {
    const data = await api<{ message: string }>(`/batches/${batchId}/recheck`, {
      method: 'POST',
      body: JSON.stringify({ values: { 触发说明: '容差更正后复核重算' } }),
    })
    await reload()
    if (trace.value) await runTrace()
    flash(data.message)
  } catch (error) {
    flash(error instanceof Error ? error.message : '复核重算失败', false)
  }
}

function openDispositionModal(anm: Row) {
  Object.assign(dispositionForm, {
    异常id: anm.id,
    异常编号: anm.异常编号,
    首报版本号: anm.首报版本号,
    处理人: '',
    处置动作: '',
    处置说明: '',
  })
  showDispositionModal.value = true
}

async function submitDisposition() {
  try {
    const data = await api<{ message: string }>(`/anomalies/${dispositionForm.异常id}/dispositions`, {
      method: 'POST',
      body: JSON.stringify({ values: { 处理人: dispositionForm.处理人, 处置动作: dispositionForm.处置动作, 处置说明: dispositionForm.处置说明 } }),
    })
    showDispositionModal.value = false
    await reload()
    flash(data.message || '处置已派出')
  } catch (error) {
    flash(error instanceof Error ? error.message : '处置派出失败', false)
  }
}

async function resolveConflict(dsp: Row, decision: string) {
  try {
    const data = await api<{ message: string }>(`/dispositions/${dsp.id}/conflict`, {
      method: 'POST',
      body: JSON.stringify({ values: { decision, 处理人: dsp.处理人 } }),
    })
    await reload()
    if (trace.value) await runTrace()
    flash(data.message)
  } catch (error) {
    flash(error instanceof Error ? error.message : '冲突处理失败', false)
  }
}

async function runTrace() {
  if (traceEventId.value === null || traceRuleId.value === null) {
    flash('请先选择事件与规则', false)
    return
  }
  try {
    trace.value = await api(`/trace?event_id=${traceEventId.value}&rule_id=${traceRuleId.value}`)
  } catch (error) {
    flash(error instanceof Error ? error.message : '回查失败', false)
  }
}

onMounted(async () => {
  await reload()
  await runTrace()
})
</script>

<style scoped>
.qc-tabs { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.qc-tab { border: 1px solid var(--border); background: #fff; border-radius: 6px; padding: 6px 14px; cursor: pointer; font-size: 13px; }
.qc-tab.active { background: var(--brand); border-color: var(--brand); color: #fff; }
.qc-panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.qc-panel h4 { margin: 16px 0 8px; font-size: 14px; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; }
.badge.pass { background: #e7f6ec; color: #1a7f37; }
.badge.fail { background: #fdecec; color: #b42318; }
.badge.block { background: #fdecec; color: #b42318; }
.badge.muted { background: #eef2f6; color: var(--muted); }
.field-chip { display: inline-block; background: #eef2f6; border-radius: 4px; padding: 2px 6px; margin: 2px; font-size: 12px; }
.chain-list { margin: 0; padding-left: 16px; font-size: 12px; color: var(--muted); }
.chain-list li { margin-bottom: 2px; }
.trace-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 8px; }
.info-text { color: #1a7f37; font-size: 13px; }
select { padding: 7px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; background: #fff; }
</style>
